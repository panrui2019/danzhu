import sqlite3
import datetime
import os
import time
import json
import random
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

# 配置 Flask
app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

DB_FILE = 'gamedata.db'
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit

# 确保上传目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# 定义所有预置地图配置 (Key, Name) - 这些是硬编码在前端的
DEFAULT_MAPS = [
    ('CLASSIC_CHAOS', '混乱森林 (经典)'),
    ('GALTON_BOARD', '高尔顿三角'),
    ('MOVING_GUARDS', '橡胶守卫'),
    ('BUMPER_CITY', '疯狂碰碰城'),
    ('LUCKY_FUNNEL', '幸运大漏斗'),
    ('HEART_MAZE', '爱心迷阵'),
    ('RAINBOW_STAIRS', '彩虹阶梯'),
    ('SMILEY_FACE', '笑脸乐园'),
    ('SPIRAL_GALAXY', '螺旋星系'),
    ('DIAMOND_MINE', '钻石矿坑'),
    ('PACHINKO_FOREST', '日式柏青哥'),
    ('BINARY_TREE', '二叉树抉择'),
    ('METEOR_SHOWER', '陨石雨'),
    ('DOUBLE_CROSS', '双重十字'),
    ('THE_CAGE', '困兽之笼'),
    ('SLALOM_RUN', '极限回旋'),
    ('CHAOS_VORTEX', '混沌漩涡'),
    ('SPACE_INVADERS', '太空入侵者'),
    ('PINBALL_WIZARD', '弹珠巫师'),
    ('DNA_HELIX', '双螺旋DNA'),
    ('PLINKO_PYRAMID', '普林科金字塔'),
    ('BLACK_HOLE', '黑洞引力'),
    ('TIMELINE_RIVER', '时光之河'),
    ('BONUS_COIN_FIELD', '💰 奖励关卡 (满屏金币)')
]


def init_db():
    """初始化数据库"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. 用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            email TEXT,
            coins INTEGER DEFAULT 100,
            tickets INTEGER DEFAULT 0,
            current_skin TEXT DEFAULT "default"
        )
    ''')
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN current_skin TEXT DEFAULT "default"')
    except:
        pass

    # 2. 兑换码表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY,
            max_uses INTEGER DEFAULT 1,
            current_uses INTEGER DEFAULT 0,
            target_user TEXT,
            reward_amount INTEGER DEFAULT 100,
            last_used_time TIMESTAMP
        )
    ''')

    # 3. 礼物表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            image_url TEXT,
            price INTEGER DEFAULT 100, 
            stock INTEGER DEFAULT 0,   
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 4. 兑换记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gift_redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            gift_id INTEGER,
            gift_name TEXT, 
            cost INTEGER,
            redeem_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'success' 
        )
    ''')

    # 5. 地图配置表 - 增加 weight, data (JSON), author 字段
    # key 对于自定义地图将是 UUID 或时间戳
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS maps (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            weight INTEGER DEFAULT 10,
            data TEXT, 
            author TEXT DEFAULT 'System',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 尝试添加新字段（如果不存在）
    try:
        cursor.execute('ALTER TABLE maps ADD COLUMN weight INTEGER DEFAULT 10')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE maps ADD COLUMN data TEXT')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE maps ADD COLUMN author TEXT DEFAULT "System"')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE maps ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
    except:
        pass

    # 6. 皮肤配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS skins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            image_url TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        )
    ''')

    # 7. 游戏参数配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    # 8. 转账记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transfer_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            receiver TEXT,
            amount INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 初始化默认配置
    default_configs = {
        'slot_count': '14',
        'light_rules': json.dumps({"1": 5, "2": 10, "3": 20, "4": 30, "5": 35}),
        'multiplier_rules': json.dumps({"1": 10, "2": 5, "3": 4, "4": 3, "5": 2}),
        'lucky_wheel': json.dumps({"enabled": True, "min": -50, "max": 200, "prob": 0.4}),
        'bomb_config': json.dumps({"prob": 0.3, "count_min": 1, "count_max": 3}),
        'coin_config': json.dumps({
            "temp_prob": 0.5, "temp_min": 2, "temp_max": 5, "temp_val": 10,
            "fixed_prob": 0.3, "fixed_min": 1, "fixed_max": 3, "fixed_val": 5
        }),
        'egg_config': json.dumps({
            "appear_prob": 0.2,
            "count_min": 1,
            "count_max": 1,
            "probs": {"coin": 0.4, "ticket": 0.4, "mouse": 0.2},
            "rewards": {"coin": 100, "ticket": 50},
            "penalties": {"coin": 50, "ticket": 20}
        }),
        'exchange_rate': '0.1',
        # AI & TTS Defaults
        'ai_voice_enabled': 'true',
        'openai_api_endpoint': 'https://api.openai.com/v1/chat/completions',
        'openai_api_key': 'YOUR_API_KEY_HERE',
        'ai_max_tokens': '60',
        'tts_mode': 'client',  # 'server' or 'client'
        'tts_api_endpoint': 'http://101.200.77.239:7530/api/v1/tts/generate',
        'tts_voice_name': 'zh-CN-YunxiNeural',
        'tts_audio_local_path': '/vol3/1000/ssd2/appdata/easyvoice/audio'
    }

    for k, v in default_configs.items():
        try:
            cursor.execute('INSERT INTO game_config (key, value) VALUES (?, ?)', (k, v))
        except sqlite3.IntegrityError:
            pass

    # 初始化默认地图数据 (如果不存在则插入)
    for key, name in DEFAULT_MAPS:
        try:
            cursor.execute('INSERT INTO maps (key, name, is_active, weight, author) VALUES (?, ?, 1, 10, "System")',
                           (key, name))
        except sqlite3.IntegrityError:
            pass

    try:
        cursor.execute('INSERT INTO users (username, password, email, coins, tickets) VALUES (?, ?, ?, ?, ?)',
                       ('admin', '123456', 'admin@test.com', 9999, 100))
    except sqlite3.IntegrityError:
        pass

    conn.commit()
    conn.close()
    print("数据库初始化完成")


# --- 路由 ---

@app.route('/')
def index():
    return send_from_directory('templates', 'game.html')


@app.route('/editor')
def editor():
    return send_from_directory('templates', 'map.html')


@app.route('/ops')
def ops():
    return send_from_directory('templates', 'ops.html')


@app.route('/<path:filename>')
def serve_any_file(filename):
    try:
        return send_from_directory('templates', filename)
    except FileNotFoundError:
        return "File not found", 404


# --- 游戏参数配置 API ---

@app.route('/api/config', methods=['GET'])
def get_game_config():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM game_config WHERE key != 'openai_api_key'").fetchall()
    conn.close()
    config = {}
    for row in rows:
        try:
            config[row['key']] = json.loads(row['value'])
        except (json.JSONDecodeError, TypeError):
            config[row['key']] = row['value']
    return jsonify(config)


# --- 地图管理 API (核心更新) ---

@app.route('/api/maps', methods=['GET'])
def get_all_maps():
    conn = get_db_connection()
    maps = conn.execute('SELECT * FROM maps').fetchall()
    conn.close()
    return jsonify([dict(m) for m in maps])


@app.route('/api/map/<key>', methods=['GET'])
def get_map_by_key(key):
    conn = get_db_connection()
    game_map = conn.execute('SELECT * FROM maps WHERE key = ?', (key,)).fetchone()
    conn.close()
    if game_map:
        return jsonify(dict(game_map))
    return jsonify({'success': False, 'message': 'Map not found'}), 404


@app.route('/api/active_maps', methods=['GET'])
def get_active_maps():
    conn = get_db_connection()
    # 返回 active 的地图，必须包含 data (用于自定义地图渲染)
    maps = conn.execute('SELECT key, name, weight, data, author FROM maps WHERE is_active = 1').fetchall()
    conn.close()
    return jsonify([dict(m) for m in maps])


@app.route('/api/maps/save', methods=['POST'])
def save_custom_map():
    data = request.json
    name = data.get('name', '未命名地图')
    author = data.get('author', '匿名工匠')
    map_json = json.dumps(data.get('data', {}))  # 核心地图数据

    # 生成唯一 Key
    map_key = f"CUSTOM_{int(time.time())}_{random.randint(100, 999)}"

    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO maps (key, name, is_active, weight, data, author) VALUES (?, ?, 1, 10, ?, ?)',
            (map_key, name, map_json, author)
        )
        conn.commit()
        return jsonify({'success': True, 'message': '地图保存成功！已自动上架。', 'key': map_key})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()


@app.route('/api/maps/update', methods=['POST'])
def update_custom_map():
    data = request.json
    key = data.get('key')
    name = data.get('name')
    author = data.get('author')
    map_data = json.dumps(data.get('data', {}))

    if not key:
        return jsonify({'success': False, 'message': 'Map key is required'}), 400

    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE maps SET name = ?, author = ?, data = ? WHERE key = ?',
            (name, author, map_data, key)
        )
        conn.commit()
        return jsonify({'success': True, 'message': '地图更新成功！'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()


# --- 皮肤系统 API ---
@app.route('/api/skins', methods=['GET'])
def get_skins():
    conn = get_db_connection()
    is_admin = request.args.get('all') == '1'
    sql = 'SELECT * FROM skins ORDER BY id DESC' if is_admin else 'SELECT * FROM skins WHERE is_active = 1 ORDER BY id DESC'
    skins = conn.execute(sql).fetchall()
    conn.close()
    return jsonify([dict(s) for s in skins])


@app.route('/api/set_skin', methods=['POST'])
def set_skin():
    data = request.json
    conn = get_db_connection()
    conn.execute('UPDATE users SET current_skin = ? WHERE username = ?', (data.get('skin_url'), data.get('username')))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# --- 用户认证与信息 API ---
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username=? AND password=?',
                        (data.get('username'), data.get('password'))).fetchone()
    conn.close()
    if user: return jsonify({'success': True, 'data': dict(user)})
    return jsonify({'success': False, 'message': '用户名或密码错误'})


@app.route('/api/my_info', methods=['GET'])
def get_my_info():
    username = request.args.get('username')
    conn = get_db_connection()
    user = conn.execute('SELECT username, coins, tickets, current_skin FROM users WHERE username=?',
                        (username,)).fetchone()
    conn.close()
    if user: return jsonify({'success': True, 'data': dict(user)})
    return jsonify({'success': False, 'message': '用户未找到'})


@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    conn = get_db_connection()
    try:
        exist = conn.execute('SELECT 1 FROM users WHERE username=? OR email=?', (username, email)).fetchone()
        if exist: return jsonify({'success': False, 'message': '用户或邮箱已存在'})
        conn.execute('INSERT INTO users (username, password, email, coins, tickets) VALUES (?, ?, ?, ?, ?)',
                     (username, password, email, 100, 0))
        conn.commit()
        return jsonify({'success': True, 'message': '注册成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()


@app.route('/api/update', methods=['POST'])
def update_data():
    data = request.json
    conn = get_db_connection()
    conn.execute('UPDATE users SET coins=?, tickets=? WHERE username=?',
                 (data.get('coins'), data.get('tickets'), data.get('username')))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/simple_users', methods=['GET'])
def get_simple_users():
    conn = get_db_connection()
    users = conn.execute('SELECT username FROM users').fetchall()
    conn.close()
    return jsonify([u['username'] for u in users])


@app.route('/api/recent_contacts', methods=['GET'])
def get_recent_contacts():
    sender = request.args.get('username')
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT receiver, MAX(timestamp) as last_time FROM transfer_logs WHERE sender = ? GROUP BY receiver ORDER BY last_time DESC LIMIT 5',
        (sender,)).fetchall()
    conn.close()
    return jsonify([r['receiver'] for r in rows])


@app.route('/api/transfer_tickets', methods=['POST'])
def transfer_tickets():
    data = request.json
    from_user = data.get('from_user')
    to_user = data.get('to_user')
    amount = int(data.get('amount', 0))
    if amount <= 0: return jsonify({'success': False, 'message': '数额必须大于0'})
    conn = get_db_connection()
    try:
        sender = conn.execute('SELECT tickets FROM users WHERE username=?', (from_user,)).fetchone()
        if not sender or sender['tickets'] < amount: return jsonify({'success': False, 'message': '积分不足'})
        if not conn.execute('SELECT 1 FROM users WHERE username=?', (to_user,)).fetchone(): return jsonify(
            {'success': False, 'message': '接收用户不存在'})
        conn.execute('UPDATE users SET tickets = tickets - ? WHERE username = ?', (amount, from_user))
        conn.execute('UPDATE users SET tickets = tickets + ? WHERE username = ?', (amount, to_user))
        conn.execute('INSERT INTO transfer_logs (sender, receiver, amount) VALUES (?, ?, ?)',
                     (from_user, to_user, amount))
        conn.commit()
        new_tickets = conn.execute('SELECT tickets FROM users WHERE username=?', (from_user,)).fetchone()['tickets']
        return jsonify({'success': True, 'message': '赠送成功', 'new_tickets': new_tickets})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()


@app.route('/api/exchange_points', methods=['POST'])
def exchange_points():
    data = request.json
    username = data.get('username')
    points = int(data.get('points', 0))
    conn = get_db_connection()
    try:
        config_row = conn.execute('SELECT value FROM game_config WHERE key = "exchange_rate"').fetchone()
        rate = float(config_row['value']) if config_row else 0.1
        coins = int(points * rate)
        if coins <= 0: return jsonify({'success': False, 'message': '积分太少'})
        user = conn.execute('SELECT tickets, coins FROM users WHERE username=?', (username,)).fetchone()
        if not user or user['tickets'] < points: return jsonify({'success': False, 'message': '积分不足'})
        conn.execute('UPDATE users SET tickets = tickets - ?, coins = coins + ? WHERE username = ?',
                     (points, coins, username))
        conn.commit()
        new_user = conn.execute('SELECT tickets, coins FROM users WHERE username=?', (username,)).fetchone()
        return jsonify({'success': True, 'message': '兑换成功', 'new_tickets': new_user['tickets'],
                        'new_coins': new_user['coins']})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()


@app.route('/api/gifts', methods=['GET'])
def get_gifts():
    conn = get_db_connection()
    gifts = conn.execute('SELECT * FROM gifts WHERE stock > 0 ORDER BY price ASC').fetchall()
    conn.close()
    return jsonify([dict(g) for g in gifts])


@app.route('/api/exchange_gift', methods=['POST'])
def exchange_gift():
    data = request.json
    username, gift_id = data.get('username'), data.get('gift_id')
    conn = get_db_connection()
    try:
        user = conn.execute('SELECT tickets FROM users WHERE username=?', (username,)).fetchone()
        gift = conn.execute('SELECT * FROM gifts WHERE id=?', (gift_id,)).fetchone()
        if not user or not gift: return jsonify({'success': False, 'message': '错误'})
        if gift['stock'] <= 0 or user['tickets'] < gift['price']: return jsonify(
            {'success': False, 'message': '库存或积分不足'})
        conn.execute('UPDATE gifts SET stock = stock - 1 WHERE id = ?', (gift_id,))
        conn.execute('UPDATE users SET tickets = tickets - ? WHERE username = ?', (gift['price'], username))
        conn.execute('INSERT INTO gift_redemptions (user_id, gift_id, gift_name, cost) VALUES (?, ?, ?, ?)',
                     (username, gift_id, gift['name'], gift['price']))
        conn.commit()
        return jsonify({'success': True, 'message': '兑换成功', 'new_tickets': user['tickets'] - gift['price']})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()


@app.route('/api/my_redemptions', methods=['GET'])
def my_redemptions():
    conn = get_db_connection()
    logs = conn.execute('SELECT * FROM gift_redemptions WHERE user_id=? ORDER BY redeem_time DESC',
                        (request.args.get('username'),)).fetchall()
    conn.close()
    return jsonify([dict(l) for l in logs])


@app.route('/api/redeem', methods=['POST'])
def redeem_code():
    data = request.json
    username, code = data.get('username'), data.get('code')
    conn = get_db_connection()
    try:
        c = conn.execute('SELECT * FROM redeem_codes WHERE code=?', (code,)).fetchone()
        if not c or c['current_uses'] >= c['max_uses'] or (c['target_user'] and c['target_user'] != username):
            return jsonify({'success': False, 'message': '无效或已过期的兑换码'})
        amt = c['reward_amount'] or 100
        conn.execute('UPDATE redeem_codes SET current_uses=current_uses+1, last_used_time=? WHERE code=?',
                     (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), code))
        conn.execute('UPDATE users SET coins=coins+? WHERE username=?', (amt, username))
        conn.commit()
        new_coins = conn.execute('SELECT coins FROM users WHERE username=?', (username,)).fetchone()['coins']
        return jsonify({'success': True, 'message': f'成功! +{amt}金币', 'new_coins': new_coins})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()


@app.route('/api/leaderboard', methods=['GET'])
def leaderboard():
    conn = get_db_connection()
    top = conn.execute('SELECT username, tickets FROM users ORDER BY tickets DESC LIMIT 10').fetchall()
    my_u = request.args.get('username')
    my_rank, my_tickets = 0, 0
    if my_u:
        u = conn.execute('SELECT tickets FROM users WHERE username=?', (my_u,)).fetchone()
        if u:
            my_tickets = u['tickets']
            my_rank = conn.execute('SELECT COUNT(*) as c FROM users WHERE tickets > ?', (my_tickets,)).fetchone()[
                          'c'] + 1
    conn.close()
    return jsonify({'leaderboard': [dict(u) for u in top], 'my_rank': my_rank, 'my_tickets': my_tickets})


# --- AI Voice & Audio Proxy API ---

@app.route('/api/audio/<path:filename>')
def serve_tts_audio(filename):
    conn = get_db_connection()
    config_row = conn.execute('SELECT value FROM game_config WHERE key = "tts_audio_local_path"').fetchone()
    conn.close()
    if not config_row or not config_row['value']:
        print("[AUDIO PROXY] ERROR: TTS audio local path not configured in database.")
        return "TTS audio path not configured", 404

    directory = config_row['value']

    # Basic security check to prevent directory traversal.
    if '..' in filename or filename.startswith('/'):
        print(f"[AUDIO PROXY] ERROR: Invalid filename requested (directory traversal attempt): {filename}")
        return "Invalid filename", 400

    print(f"[AUDIO PROXY] Attempting to serve file. Directory: '{directory}', Filename: '{filename}'")
    full_path = os.path.join(directory, filename)
    print(f"[AUDIO PROXY] Full path: '{full_path}'")

    if not os.path.exists(full_path):
        print(f"[AUDIO PROXY] ERROR: File not found at path: {full_path}")
        return "Audio file not found.", 404

    try:
        return send_from_directory(directory, filename, as_attachment=False)
    except Exception as e:
        print(f"[AUDIO PROXY] ERROR: Failed to send file. Error: {e}")
        return "Error sending file.", 500


@app.route('/api/ai_text_line', methods=['POST'])
def get_ai_text_line():
    print("\n--- [AI TEXT] Request Initiated ---")
    conn = get_db_connection()
    configs = {row['key']: row['value'] for row in conn.execute('SELECT key, value FROM game_config').fetchall()}
    conn.close()

    ai_enabled_str = configs.get('ai_voice_enabled', 'false')
    if ai_enabled_str.lower() != 'true':
        return jsonify({'success': False, 'message': 'AI feature is disabled.'})

    data = request.json
    OPENAI_API_ENDPOINT = configs.get('openai_api_endpoint')
    OPENAI_API_KEY = configs.get('openai_api_key')
    AI_MAX_TOKENS = int(configs.get('ai_max_tokens', 60))

    if not all([OPENAI_API_ENDPOINT, OPENAI_API_KEY]):
        return jsonify({'success': False, 'message': 'AI service is not configured.'}), 500

    system_prompt = f"""
你是一个轻松幽默的游戏搭子，你的名字叫“弹珠精灵”。你正在和一个玩家互动，他刚刚玩完一局“七彩弹珠”游戏。
你的任务是根据玩家当前的游戏状态、本局游戏事件，并结合最近的整体游戏历史，给出一句简短的、口语化的互动评论。
请优先分析“本局事件”，如果本局事件足够精彩（汇总这一局的信息，比如中大奖、踩炸弹、中转盘、损失大量金币、赢大量金币、遇到特殊事件），就优先评论本局。
如果本局很平淡，可以回顾“历史事件”来进行吐槽或鼓励（比如总是差一点中奖，或者运气一直很好/很差，或者连续失败，连续胜利，连续踩炸弹等，该引导下注时就引导，该劝玩家收手时就收手）。
事件说明：

- **风格**：俏皮、可爱、幽默、吐槽、鼓励，随机应变。
- **长度**：严格控制在30个汉字以内，1-2句话。
- **禁止**：不要说教，不要提出具体游戏建议，不要暴露你是AI，不要包含任何表情符号或特殊符号。
- **输出**：直接输出评论文本。
"""
    user_prompt = f"""
    - 我的状态：{data.get('coins')}个金币，{data.get('tickets')}张奖票。
    - 本局地图：{data.get('map')}。
    - 本局结果：{'赢了' if data.get('win') else '输了'}。
    - 本局事件: {', '.join([f"{h.get('timestamp', '')}:{h.get('message', '')}" for h in json.loads(data.get('history', '[]'))])}
    - 历史事件: {', '.join([f"{h.get('timestamp', '')}:{h.get('message', '')}" for h in json.loads(data.get('full_history', '[]'))])}
    快，说点什么！
    """

    try:
        ai_payload = {
            "model": "gemini-2.5-flash-nothinking",
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "max_tokens": AI_MAX_TOKENS, "temperature": 0.8,
        }
        print(f"[AI TEXT] request: {ai_payload}")
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        ai_response = requests.post(OPENAI_API_ENDPOINT, json=ai_payload, headers=headers, timeout=20)
        ai_response.raise_for_status()
        ai_result = ai_response.json()
        ai_text = ai_result['choices'][0]['message']['content'].strip()
        if not ai_text:
            return jsonify({'success': False, 'message': 'AI returned no content.'})
        return jsonify({'success': True, 'text': ai_text})
    except Exception as e:
        print(f"[AI TEXT] ERROR calling AI API: {e}")
        return jsonify({'success': False, 'message': 'Failed to get AI response.'})


@app.route('/api/ai_voice_line', methods=['POST'])
def get_ai_voice_line():
    print("\n--- [AI VOICE] Request Initiated ---")

    # Load config from DB
    conn = get_db_connection()
    configs = {row['key']: row['value'] for row in conn.execute('SELECT key, value FROM game_config').fetchall()}
    conn.close()

    # Check if the feature is enabled
    ai_enabled_str = configs.get('ai_voice_enabled', 'false')
    if ai_enabled_str.lower() != 'true':
        print("[AI VOICE] SKIPPED: AI voice feature is disabled in config.")
        print("--- [AI VOICE] Request Finished ---")
        return jsonify({'success': False, 'message': 'AI voice feature is disabled.'})

    # Audio Path and Cleanup
    tts_audio_path = configs.get('tts_audio_local_path')
    if not tts_audio_path or 'audio' not in tts_audio_path:
        print(f"[AI VOICE] ERROR: Invalid 'tts_audio_local_path' configured: {tts_audio_path}")
        return jsonify({'success': False, 'message': 'TTS audio path is not configured correctly.'}), 500

    try:
        if os.path.exists(tts_audio_path):
            for filename in os.listdir(tts_audio_path):
                file_path = os.path.join(tts_audio_path, filename)
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            print(f"[AI VOICE] Cleared audio cache directory: {tts_audio_path}")
    except Exception as e:
        print(f"[AI VOICE] ERROR clearing audio cache: {e}")

    data = request.json
    print(f"[AI VOICE] Request Data: {data}")

    OPENAI_API_ENDPOINT = configs.get('openai_api_endpoint')
    OPENAI_API_KEY = configs.get('openai_api_key')
    TTS_API_ENDPOINT = configs.get('tts_api_endpoint')
    TTS_VOICE_NAME = configs.get('tts_voice_name')
    AI_MAX_TOKENS = int(configs.get('ai_max_tokens', 60))

    if not all([OPENAI_API_ENDPOINT, OPENAI_API_KEY, TTS_API_ENDPOINT, TTS_VOICE_NAME]):
        print("[AI VOICE] ERROR: AI or TTS service is not configured in the database.")
        return jsonify({'success': False, 'message': 'AI or TTS service is not configured.'}), 500

    coins = data.get('coins')
    tickets = data.get('tickets')
    current_map = data.get('map')
    win = data.get('win')
    history_str = data.get('history', '[]')
    full_history_str = data.get('full_history', '[]')

    try:
        current_game_history = json.loads(history_str)
    except:
        current_game_history = []

    try:
        full_history = json.loads(full_history_str)
    except:
        full_history = []

    # 1. Construct prompt for AI
    system_prompt = f"""
你是一个轻松幽默的游戏搭子，你的名字叫“弹珠精灵”。你正在和一个玩家互动，他刚刚玩完一局“七彩弹珠”游戏。
你的任务是根据玩家当前的游戏状态、本局游戏事件，并结合最近的整体游戏历史，给出一句简短的、口语化的互动评论。
请优先分析“本局事件”，如果本局事件足够精彩（汇总这一局的信息，比如中大奖、踩炸弹、中转盘、损失大量金币、赢大量金币、遇到特殊事件），就优先评论本局。
如果本局很平淡，可以回顾“历史事件”来进行吐槽或鼓励（比如总是差一点中奖，或者运气一直很好/很差，或者连续失败，连续胜利，连续踩炸弹等，该引导下注时就引导，该劝玩家收手时就收手）。
事件说明：

- **风格**：俏皮、可爱、幽默、吐槽、鼓励，随机应变。
- **长度**：严格控制在30个汉字以内，1-2句话。
- **禁止**：不要说教，不要提出具体游戏建议，不要暴露你是AI，不要包含任何表情符号或特殊符号。
- **输出**：直接输出评论文本。
"""

    user_prompt = f"""
    - 我的状态：{coins}个金币，{tickets}张奖票。
    - 本局地图：{current_map}。
    - 本局结果：{'赢了' if win else '输了'}。
    - 本局事件: {', '.join([f"{h.get('timestamp', '')}:{h.get('message', '')}" for h in current_game_history])}
    - 历史事件: {', '.join([f"{h.get('timestamp', '')}:{h.get('message', '')}" for h in full_history])}
    快，说点什么！
    """
    print(f"[AI VOICE] Constructed User Prompt:\n{user_prompt}")

    # 2. Call OpenAI-compatible API
    ai_text = ""
    try:
        ai_payload = {
            "model": "gemini-2.5-flash-nothinking",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": AI_MAX_TOKENS,
            "temperature": 0.8,
        }
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        print(f"[AI VOICE] Calling AI API at {OPENAI_API_ENDPOINT}")
        print(f"[AI VOICE] requestbody：\n{ai_payload}")

        ai_response = requests.post(OPENAI_API_ENDPOINT, json=ai_payload, headers=headers, timeout=20)
        ai_response.raise_for_status()
        ai_result = ai_response.json()
        ai_text = ai_result['choices'][0]['message']['content'].strip()
        print(f"[AI VOICE] AI API Response Text: '{ai_result}'")

        # Handle case where AI returns an empty string
        if not ai_text:
            print("[AI VOICE] WARNING: AI returned an empty string. Skipping TTS call.")
            print("--- [AI VOICE] Request Finished (No Content) ---")
            return jsonify({'success': False, 'message': 'AI returned no content.'})

    except Exception as e:
        print(f"[AI VOICE] ERROR calling AI API: {e}")
        ai_text = "哎呀，网络好像有点卡顿！"
        return jsonify({'success': False, 'message': str(e)})

    # 3. Call TTS API
    try:
        tts_payload = {
            "text": ai_text,
            "voice": TTS_VOICE_NAME,
            "rate": "0%",
            "pitch": "0Hz",
            "volume": "0%"
        }
        print(f"[AI VOICE] Calling TTS API at {TTS_API_ENDPOINT} with payload: {tts_payload}")
        tts_response = requests.post(TTS_API_ENDPOINT, json=tts_payload, timeout=10)
        tts_response.raise_for_status()
        tts_result = tts_response.json()
        print(f"[AI VOICE] TTS API Response: {tts_result}")

        if tts_result.get("success"):
            relative_audio_path = tts_result.get("data", {}).get("file")
            if relative_audio_path:
                # Ensure we only have the filename, not a full path
                safe_relative_path = os.path.basename(relative_audio_path)
                proxied_audio_url = f"/api/audio/{safe_relative_path}"
                response_payload = {'success': True, 'audio_url': proxied_audio_url, 'text': ai_text}
                print(f"[AI VOICE] Success! Sending final response to client: {response_payload}")
                print("--- [AI VOICE] Request Finished ---")
                return jsonify(response_payload)

    except Exception as e:
        print(f"[AI VOICE] ERROR calling TTS API: {e}")
        print("--- [AI VOICE] Request Finished with Error ---")
        return jsonify({'success': False, 'message': 'TTS service failed.'}), 500

    print("[AI VOICE] ERROR: Failed to generate audio, falling through.")
    print("--- [AI VOICE] Request Finished with Error ---")
    return jsonify({'success': False, 'message': 'Failed to generate audio.'}), 500


# --- 管理员 API ---

@app.route('/api/admin/update_config', methods=['POST'])
def update_game_config():
    data = request.json
    conn = get_db_connection()
    try:
        for key, value in data.items():
            # Don't save empty API keys unless they are explicitly cleared
            if key == 'openai_api_key' and not value:
                # Check if a key already exists, if so, don't overwrite with empty
                existing = conn.execute('SELECT value FROM game_config WHERE key = ?', (key,)).fetchone()
                if existing and existing['value'] and 'YOUR_API_KEY_HERE' not in existing['value']:
                    continue

            str_val = json.dumps(value) if isinstance(value, (dict, list, bool)) else str(value)
            conn.execute('INSERT OR REPLACE INTO game_config (key, value) VALUES (?, ?)', (key, str_val))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()


@app.route('/api/admin/toggle_map', methods=['POST'])
def toggle_map():
    data = request.json
    key = data.get('key')
    active = 1 if data.get('active') else 0
    conn = get_db_connection()
    conn.execute('UPDATE maps SET is_active = ? WHERE key = ?', (active, key))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/admin/delete_map', methods=['POST'])
def delete_map():
    data = request.json
    key = data.get('key')
    is_default = any(def_key == key for def_key, _ in DEFAULT_MAPS)
    if is_default:
        return jsonify({'success': False, 'message': '系统预置地图不可删除'})
    conn = get_db_connection()
    conn.execute('DELETE FROM maps WHERE key = ?', (key,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/admin/update_map_weight', methods=['POST'])
def update_map_weight():
    data = request.json
    key = data.get('key')
    weight = int(data.get('weight', 10))
    if weight < 0: weight = 0
    conn = get_db_connection()
    conn.execute('UPDATE maps SET weight = ? WHERE key = ?', (weight, key))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/admin/add_skin', methods=['POST'])
def add_skin():
    try:
        name = request.form.get('name')
        if 'image' not in request.files: return jsonify({'success': False, 'message': '请上传图片'})
        file = request.files['image']
        if file and allowed_file(file.filename):
            filename = secure_filename(f"skin_{int(time.time())}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_url = f"/static/uploads/{filename}"
            conn = get_db_connection()
            conn.execute('INSERT INTO skins (name, image_url) VALUES (?, ?)', (name, image_url))
            conn.commit()
            conn.close()
            return jsonify({'success': True})
        return jsonify({'success': False, 'message': '图片格式不支持'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/admin/toggle_skin', methods=['POST'])
def toggle_skin():
    data = request.json
    conn = get_db_connection()
    conn.execute('UPDATE skins SET is_active = ? WHERE id = ?', (data.get('is_active'), data.get('id')))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/admin/delete_skin', methods=['POST'])
def delete_skin():
    data = request.json
    conn = get_db_connection()
    conn.execute('DELETE FROM skins WHERE id = ?', (data.get('id'),))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/admin/add_gift', methods=['POST'])
def add_gift():
    try:
        name = request.form.get('name')
        price = int(request.form.get('price'))
        stock = int(request.form.get('stock'))
        image_url = ''
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"{int(datetime.datetime.now().timestamp())}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_url = f"/static/uploads/{filename}"
        conn = get_db_connection()
        conn.execute('INSERT INTO gifts (name, image_url, price, stock) VALUES (?, ?, ?, ?)',
                     (name, image_url, price, stock))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/admin/update_gift', methods=['POST'])
def update_gift():
    try:
        gift_id = request.form.get('id')
        name = request.form.get('name')
        price = request.form.get('price')
        stock = request.form.get('stock')
        conn = get_db_connection()
        if 'image' in request.files and request.files['image'].filename != '':
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"{int(datetime.datetime.now().timestamp())}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_url = f"/static/uploads/{filename}"
                conn.execute('UPDATE gifts SET name=?, price=?, stock=?, image_url=? WHERE id=?',
                             (name, price, stock, image_url, gift_id))
        else:
            conn.execute('UPDATE gifts SET name=?, price=?, stock=? WHERE id=?', (name, price, stock, gift_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/admin/gifts', methods=['GET'])
def admin_get_gifts():
    conn = get_db_connection()
    gifts = conn.execute('SELECT * FROM gifts ORDER BY id DESC').fetchall()
    conn.close()
    return jsonify([dict(g) for g in gifts])


@app.route('/api/admin/redemptions', methods=['GET'])
def admin_redemptions():
    conn = get_db_connection()
    logs = conn.execute('SELECT * FROM gift_redemptions ORDER BY redeem_time DESC LIMIT 100').fetchall()
    conn.close()
    return jsonify([dict(l) for l in logs])


@app.route('/api/admin/users', methods=['GET'])
def admin_get_users():
    search = request.args.get('search', '')
    conn = get_db_connection()
    if search:
        users = conn.execute("SELECT * FROM users WHERE username LIKE ? OR email LIKE ?",
                             (f'%{search}%', f'%{search}%')).fetchall()
    else:
        users = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])


@app.route('/api/admin/update_user', methods=['POST'])
def admin_update_user():
    data = request.json
    conn = get_db_connection()
    conn.execute('UPDATE users SET coins=?, tickets=? WHERE username=?',
                 (data.get('coins'), data.get('tickets'), data.get('username')))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/admin/codes', methods=['GET', 'POST'])
def admin_codes():
    conn = get_db_connection()
    if request.method == 'GET':
        codes = conn.execute("SELECT * FROM redeem_codes ORDER BY last_used_time DESC").fetchall()
        conn.close()
        return jsonify([dict(c) for c in codes])
    else:
        data = request.json
        try:
            conn.execute('INSERT INTO redeem_codes (code, max_uses, target_user, reward_amount) VALUES (?, ?, ?, ?)',
                         (data.get('code'), data.get('max_uses', 1), data.get('target_user', ''),
                          data.get('reward_amount', 100)))
            conn.commit()
            conn.close()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})


@app.route('/api/admin/update_code', methods=['POST'])
def update_code():
    data = request.json
    conn = get_db_connection()
    try:
        conn.execute('UPDATE redeem_codes SET max_uses=?, target_user=?, reward_amount=? WHERE code=?',
                     (data.get('max_uses'), data.get('target_user'), data.get('reward_amount'), data.get('code')))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


if __name__ == '__main__':
    init_db()
    print("Server running on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)