from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from functools import wraps

app = Flask(__name__)
app.secret_key = "roadassist_secret_key"
DATABASE = "roadassist.db"

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def create_database():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            vehicle_no TEXT,
            vehicle_type TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            problem TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            rating INTEGER,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

create_database()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        vehicle_no = request.form.get("vehicle_no", "").strip()
        vehicle_type = request.form.get("vehicle_type", "").strip()

        if not all([name, phone, email, password, vehicle_no, vehicle_type]):
            return render_template("register.html", error="Please fill all fields.")

        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO users
                (name, phone, email, password, vehicle_no, vehicle_type)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, phone, email, password, vehicle_no, vehicle_type))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return render_template("register.html", error="Email already registered.")
        conn.close()

        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ? AND password = ?",
            (email, password)
        ).fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

        return render_template("login.html", error="Invalid email or password.")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user_name=session.get("user_name"))

@app.route("/submit-request", methods=["POST"])
@login_required
def submit_request():
    data = request.get_json(silent=True) or {}
    problem = data.get("problem")
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if not problem:
        return jsonify({"success": False, "message": "Please select a problem."}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO requests
        (user_id, problem, latitude, longitude, status)
        VALUES (?, ?, ?, ?, 'Pending')
    """, (session["user_id"], problem, latitude, longitude))
    request_id = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": "Request submitted successfully.",
        "request_id": request_id
    })

@app.route("/latest-request")
@login_required
def latest_request():
    conn = get_db()
    row = conn.execute("""
        SELECT id, problem, latitude, longitude, status, created_at
        FROM requests
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (session["user_id"],)).fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "message": "No request found."})

    return jsonify({"success": True, **dict(row)})

@app.route("/mechanic")
def mechanic():
    return render_template("mechanic.html")

@app.route("/mechanic-requests")
def mechanic_requests():
    conn = get_db()
    rows = conn.execute("""
        SELECT
            r.id,
            r.problem,
            r.latitude,
            r.longitude,
            r.status,
            r.created_at,
            u.name AS customer_name,
            u.phone,
            u.vehicle_no,
            u.vehicle_type
        FROM requests r
        LEFT JOIN users u ON r.user_id = u.id
        WHERE r.status IN ('Pending', 'Accepted')
        ORDER BY r.id DESC
    """).fetchall()
    conn.close()

    return jsonify([dict(row) for row in rows])

@app.route("/accept-request/<int:request_id>", methods=["POST"])
def accept_request(request_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE requests
        SET status = 'Accepted'
        WHERE id = ? AND status = 'Pending'
    """, (request_id,))
    conn.commit()
    changed = cur.rowcount
    conn.close()

    if changed == 0:
        return jsonify({"success": False, "message": "Request is no longer pending."}), 400

    return jsonify({"success": True, "message": "Request accepted successfully."})

@app.route("/complete-request/<int:request_id>", methods=["POST"])
def complete_request(request_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE requests
        SET status = 'Completed'
        WHERE id = ? AND status = 'Accepted'
    """, (request_id,))
    conn.commit()
    changed = cur.rowcount
    conn.close()

    if changed == 0:
        return jsonify({"success": False, "message": "Request cannot be completed."}), 400

    return jsonify({"success": True, "message": "Service completed successfully."})

@app.route("/submit-feedback", methods=["POST"])
@login_required
def submit_feedback():
    data = request.get_json(silent=True) or {}

    try:
        request_id = int(data.get("request_id"))
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid feedback data."}), 400

    message = (data.get("comment") or data.get("message") or "").strip()

    if rating < 1 or rating > 5:
        return jsonify({"success": False, "message": "Rating must be between 1 and 5."}), 400

    conn = get_db()
    req = conn.execute("""
        SELECT id FROM requests
        WHERE id = ? AND user_id = ? AND status = 'Completed'
    """, (request_id, session["user_id"])).fetchone()

    if not req:
        conn.close()
        return jsonify({"success": False, "message": "Complete the service before giving feedback."}), 400

    old = conn.execute(
        "SELECT id FROM feedback WHERE request_id = ?",
        (request_id,)
    ).fetchone()

    if old:
        conn.close()
        return jsonify({"success": False, "message": "Feedback already submitted."}), 400

    conn.execute("""
        INSERT INTO feedback (request_id, rating, message)
        VALUES (?, ?, ?)
    """, (request_id, rating, message))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "Thank you for your feedback!"})

if __name__ == "__main__":
    app.run(debug=True)
