from flask import Flask, render_template, request, redirect, session, url_for, flash, g
import sqlite3 # g (global) é um objeto especial do Flask para armazenar dados durante uma requisição.
from datetime import datetime
import click
from urllib.parse import urlparse
import math
import os

app = Flask(__name__)

# Configuração para produção: lê a chave secreta e a URL do banco de dados
# das variáveis de ambiente fornecidas pelo servidor de hospedagem.
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-dev-secret-key')
DATABASE_URL = os.environ.get('DATABASE_URL')

# Lista de usuários com permissão de administrador
ADMIN_USERS = ['admin', 'Joao Felix'] # Adicione aqui os nomes dos admins

# Constante para o número de posts por página
POSTS_PER_PAGE = 5


def get_db():
    """
    Abre uma nova conexão com o banco de dados se não houver uma na requisição atual.
    O objeto `g` garante que a conexão seja reutilizada durante a mesma requisição.
    """
    if 'db' not in g:
        if DATABASE_URL:
            # Conexão de produção com PostgreSQL
            g.db = psycopg2.connect(DATABASE_URL)
        else:
            # Conexão de desenvolvimento com SQLite
            g.db = sqlite3.connect('avisos.db')
            g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    """Fecha a conexão com o banco de dados ao final da requisição."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


@app.context_processor
def inject_admin_users():
    return dict(ADMIN_USERS=ADMIN_USERS)


@app.cli.command('init-db')
def init_db_command():
    """Comando para criar o banco de dados e a tabela."""
    db = get_db()
    db.execute('DROP TABLE IF EXISTS avisos') # Apaga a tabela se existir para um começo limpo
    db.execute('''
        CREATE TABLE avisos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            categoria TEXT NOT NULL,
            mensagem TEXT NOT NULL,
            data TEXT NOT NULL,
            data_evento TEXT,
            denuncias INTEGER NOT NULL DEFAULT 0
        )
    ''')
    # Otimização: Cria um índice na coluna de denúncias para acelerar a página de admin.
    db.execute('CREATE INDEX idx_denuncias ON avisos (denuncias DESC)')
    db.commit()
    click.echo('Banco de dados inicializado com sucesso.')


@app.route('/')
@app.route('/page/<int:page>')
def index(page=1):
    db = get_db()
    
    # Contar o total de avisos para calcular o número de páginas
    total_avisos = db.execute('SELECT COUNT(id) FROM avisos').fetchone()[0]
    total_pages = math.ceil(total_avisos / POSTS_PER_PAGE)
    
    # Calcular o offset para a consulta SQL
    offset = (page - 1) * POSTS_PER_PAGE
    
    # Buscar apenas os avisos para a página atual
    avisos = db.execute(
        'SELECT * FROM avisos ORDER BY id DESC LIMIT ? OFFSET ?',
        (POSTS_PER_PAGE, offset)
    ).fetchall()
    return render_template('index.html', avisos=avisos, session=session, page=page, total_pages=total_pages)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Página para o usuário se identificar."""
    if request.method == 'POST':
        # Guarda o nome do usuário na sessão
        session['usuario'] = request.form['nome']
        flash(f"Bem-vindo, {session['usuario']}!", 'success')
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    """Remove o usuário da sessão."""
    session.pop('usuario', None)
    session.pop('denunciados', None)
    flash("Você saiu com sucesso.", 'info')
    return redirect(url_for('index'))


@app.route('/postar', methods=['GET', 'POST'])
def postar():
    # Se o usuário não estiver "logado", redireciona para a página de login
    if 'usuario' not in session:
        flash("Você precisa se identificar para postar.", 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':
        nome = session['usuario'] # Pega o nome do usuário da sessão
        categoria = request.form['categoria']
        mensagem = request.form['mensagem']
        data_postagem = datetime.now().strftime('%d/%m/%Y %H:%M')

        data_evento = None
        # Se a categoria for "Evento", captura e formata a data do evento
        if categoria == 'Evento' and request.form.get('evento_dia') and request.form.get('evento_hora'):
            evento_dia = request.form.get('evento_dia') # Formato: YYYY-MM-DD
            evento_hora = request.form.get('evento_hora') # Formato: HH:MM
            data_evento_obj = datetime.strptime(f"{evento_dia} {evento_hora}", "%Y-%m-%d %H:%M")
            data_evento = data_evento_obj.strftime('%d/%m/%Y às %H:%M')

        db = get_db()
        db.execute('INSERT INTO avisos (nome, categoria, mensagem, data, data_evento) VALUES (?, ?, ?, ?, ?)',
                     (nome, categoria, mensagem, data_postagem, data_evento))
        db.commit()
        flash("Aviso postado com sucesso!", 'success')
        return redirect(url_for('index'))

    return render_template('postar.html')


@app.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar(id):
    """Exibe o formulário de edição e salva as alterações."""
    if 'usuario' not in session:
        flash("Você precisa se identificar para editar.", 'warning')
        return redirect(url_for('login'))

    db = get_db()
    aviso = db.execute('SELECT * FROM avisos WHERE id = ?', (id,)).fetchone()

    # Segurança: Garante que o aviso existe e que o usuário logado é o dono
    if not aviso or aviso['nome'] != session['usuario']:
        flash("Você não tem permissão para editar este aviso.", 'danger')
        return redirect(url_for('index')) # Redireciona se não for o dono

    if request.method == 'POST':
        categoria = request.form['categoria']
        mensagem = request.form['mensagem']
        data_evento = None

        if categoria == 'Evento' and request.form.get('evento_dia') and request.form.get('evento_hora'):
            evento_dia = request.form.get('evento_dia')
            evento_hora = request.form.get('evento_hora')
            data_evento_obj = datetime.strptime(f"{evento_dia} {evento_hora}", "%Y-%m-%d %H:%M")
            data_evento = data_evento_obj.strftime('%d/%m/%Y às %H:%M')

        db.execute('UPDATE avisos SET categoria = ?, mensagem = ?, data_evento = ? WHERE id = ?',
                     (categoria, mensagem, data_evento, id))
        db.commit()
        flash("Aviso atualizado com sucesso!", 'success')
        return redirect(url_for('index'))

    # Lógica para o método GET (exibir o formulário)
    evento_dia, evento_hora = '', ''
    if aviso['data_evento']:
        # Converte a data do banco de volta para os formatos do formulário
        data_evento_obj = datetime.strptime(aviso['data_evento'], '%d/%m/%Y às %H:%M')
        evento_dia = data_evento_obj.strftime('%Y-%m-%d')
        evento_hora = data_evento_obj.strftime('%H:%M')

    return render_template('editar.html', aviso=aviso, evento_dia=evento_dia, evento_hora=evento_hora)


@app.route('/deletar/<int:id>', methods=['POST'])
def deletar(id):
    """Deleta um aviso do banco de dados."""
    # Proteção extra: só permite deletar se o usuário estiver logado
    if 'usuario' not in session:
        flash("Você precisa se identificar para deletar.", 'warning')
        return redirect(url_for('login'))

    db = get_db()
    aviso = db.execute('SELECT nome FROM avisos WHERE id = ?', (id,)).fetchone()

    # Permite deletar se o usuário for o dono OU um admin
    if aviso and (session['usuario'] == aviso['nome'] or session.get('usuario') in ADMIN_USERS):
        db.execute('DELETE FROM avisos WHERE id = ?', (id,))
        db.commit()
        flash("Aviso deletado com sucesso.", 'success')
    else:
        flash("Você não tem permissão para deletar este aviso.", 'danger')
    
    # Redireciona de volta para a página de admin se a ação veio de lá
    if request.referrer:
        # urlparse ajuda a pegar apenas o caminho da URL anterior
        referrer_path = urlparse(request.referrer).path
        if referrer_path == url_for('admin'):
            return redirect(url_for('admin'))
            
    return redirect(url_for('index'))


@app.route('/denunciar/<int:id>', methods=['POST'])
def denunciar(id):
    """Registra uma denúncia para um aviso."""
    if 'usuario' not in session:
        flash("Você precisa se identificar para denunciar.", 'warning')
        return redirect(url_for('login'))

    # Usa setdefault para inicializar a lista na sessão se ela não existir
    denunciados = session.setdefault('denunciados', [])

    # Apenas permite a denúncia se o usuário ainda não denunciou este post
    if id not in denunciados:
        db = get_db()
        db.execute('UPDATE avisos SET denuncias = denuncias + 1 WHERE id = ?', (id,))
        db.commit()

        denunciados.append(id)
        session['denunciados'] = denunciados # Salva a lista atualizada na sessão
        flash("Sua denúncia foi registrada. Obrigado!", 'info')
    else:
        flash("Você já denunciou este aviso.", 'warning')

    return redirect(url_for('index'))


@app.route('/admin')
def admin():
    """Painel de administração para ver posts denunciados."""
    if session.get('usuario') not in ADMIN_USERS:
        flash("Você não tem permissão para acessar esta página.", 'danger')
        return redirect(url_for('index'))

    db = get_db()
    # Pega os avisos com pelo menos uma denúncia, ordenados pelos mais denunciados
    avisos_denunciados = db.execute(
        'SELECT * FROM avisos WHERE denuncias > 0 ORDER BY denuncias DESC'
    ).fetchall()

    return render_template('admin.html', avisos=avisos_denunciados)


@app.route('/admin/ignorar/<int:id>', methods=['POST'])
def ignorar_denuncia(id):
    """Reseta a contagem de denúncias de um post."""
    if session.get('usuario') not in ADMIN_USERS:
        flash("Você não tem permissão para executar esta ação.", 'danger')
        return redirect(url_for('index'))

    db = get_db()
    db.execute('UPDATE avisos SET denuncias = 0 WHERE id = ?', (id,))
    db.commit()
    flash("Denúncias ignoradas com sucesso.", 'success')

    return redirect(url_for('admin'))
