from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session, current_app
)
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from datetime import datetime
from dotenv import load_dotenv
import os, random, secrets, re, uuid
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename

# ──────────────────── App / DB setup ────────────────────
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///city_portal.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Upload folder for complaint images
app.config["UPLOAD_FOLDER"] = os.path.join(os.getcwd(), "uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# Email Setup (placeholders — set real values via environment variables)
app.config['MAIL_SERVER']   = 'smtp.gmail.com'
app.config['MAIL_PORT']     = 587                 # TLS port
app.config['MAIL_USE_TLS']  = True
app.config['MAIL_USE_SSL']  = False               # don’t enable both TLS + SSL
app.config['MAIL_USERNAME'] = 
app.config['MAIL_PASSWORD'] =  # Gmail App Password
app.config['MAIL_DEFAULT_SENDER'] = ('City Complaint Portal', 
                                     'testcitycomplaint@gmail.com')
mail = Mail(app)


# ──────────────────── Helpers ───────────────────────────
def _generate_complaint_no() -> str:
    """Generate unique 6-digit complaint number"""
    while True:
        num = f"{random.randint(100000, 999999)}"
        # Use the model query at runtime (Complaint defined later)
        if not Complaint.query.filter_by(complaint_no=num).first():
            return num


def is_valid_aadhar(aadhar: str) -> bool:
    """Return True if aadhar is exactly 12 digits."""
    return re.fullmatch(r"\d{12}", (aadhar or "").strip()) is not None


def mask_aadhar(aadhar: str) -> str:
    """Mask Aadhar as XXXX-XXXX-1234 for display."""
    if not aadhar:
        return ""
    a = str(aadhar).strip()
    if len(a) == 12 and a.isdigit():
        return f"XXXX-XXXX-{a[-4:]}"
    # Fallback: partially mask if shorter/longer
    return ("X" * max(0, len(a) - 4)) + a[-4:]


def current_citizen():
    """Return currently logged-in Citizen OR None."""
    cid = session.get("citizen_id")  # db id
    return Citizen.query.get(cid) if cid else None


# Register mask helper in Jinja templates
app.jinja_env.globals.update(mask_aadhar=mask_aadhar)


# ──────────────────── Models ────────────────────────────
class Officer(db.Model):
    __tablename__ = "officers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(500), nullable=False, unique=True)
    # Store hashed password
    password = db.Column(db.String(200), nullable=False)


class Citizen(db.Model):
    __tablename__ = "citizens"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    # store Aadhar (12-digit) instead of citizen_id
    aadhar_number = db.Column(db.String(12), nullable=False, unique=True)
    contact = db.Column(db.String(10), nullable=False)
    email = db.Column(db.String(500), nullable=False, unique=True)
    password = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500), nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)


class Complaint(db.Model):
    __tablename__ = "complaints"
    id = db.Column(db.Integer, primary_key=True)
    complaint_no = db.Column(
        db.String(6), unique=True, default=_generate_complaint_no, nullable=False
    )

    # New fields
    title = db.Column(db.String(200), nullable=False)
    location = db.Column(db.String(300), nullable=False)

    category = db.Column(db.String(100), nullable=False)
    subcategory = db.Column(db.String(100), nullable=True)
    sub_subcategory = db.Column(db.String(100), nullable=True)

    priority = db.Column(db.String(20), default="Normal", nullable=False)  # Normal / Urgent / Critical
    affected_people = db.Column(db.String(50), default="Just Me", nullable=False)

    # Existing fields
    description = db.Column(db.String(500), nullable=False)
    # store the citizen's aadhar number for traceability
    citizen_aadhar = db.Column(db.String(12), nullable=False)
    status = db.Column(db.String(50), default="Pending", nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)

    images = db.relationship("ComplaintImage", backref="complaint", lazy=True)


class ComplaintImage(db.Model):
    __tablename__ = "complaint_images"
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaints.id"), nullable=False)
    image_path = db.Column(db.String(300), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


# ──────────────────── Routes ────────────────────────────
@app.route("/")
def home():
    return render_template("index.html")


# ---------- Citizen Registration ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        contact = f.get("contact", "").strip()
        aadhar = f.get("aadhar_number", "").strip()
        address = f.get("address", "").strip()
        email = f.get("email", "").strip().lower()
        password = f.get("password", "")

        # Basic presence validation
        if not all([name, contact, aadhar, address, email, password]):
            flash("Please fill all the fields.", "danger")
            return redirect(url_for("register"))

        # contact must be 10 digits
        if not re.fullmatch(r"\d{10}", contact):
            flash("Contact must be exactly 10 digits.", "danger")
            return redirect(url_for("register"))

        # validate aadhar
        if not is_valid_aadhar(aadhar):
            flash("Aadhar must be exactly 12 digits.", "danger")
            return redirect(url_for("register"))

        # uniqueness checks
        if Citizen.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
            return redirect(url_for("register"))
        if Citizen.query.filter_by(aadhar_number=aadhar).first():
            flash("Aadhar already registered.", "danger")
            return redirect(url_for("register"))
        if Citizen.query.filter_by(contact=contact).first():
            flash("Contact number already registered.", "danger")
            return redirect(url_for("register"))

        hashed = bcrypt.generate_password_hash(password).decode()
        db.session.add(
            Citizen(
                name=name,
                contact=contact,
                aadhar_number=aadhar,
                address=address,
                email=email,
                password=hashed,
            )
        )
        db.session.commit()
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# ---------- Citizen Login ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not email or not password:
            flash("Both fields required.", "danger")
            return redirect(url_for("login"))

        usr = Citizen.query.filter_by(email=email).first()
        if not usr or not bcrypt.check_password_hash(usr.password, password):
            flash("Invalid credentials.", "danger")
            return redirect(url_for("login"))

        # store db id and aadhar in session
        session["citizen_id"], session["citizen_name"], session["citizen_aadhar"] = usr.id, usr.name, usr.aadhar_number
        flash(f"Welcome, {usr.name}!", "success")
        return redirect(url_for("citizen_dashboard"))

    return render_template("login.html")


@app.route("/citizen_dashboard")
def citizen_dashboard():
    if not current_citizen():
        flash("Please log in first.", "warning")
        return redirect(url_for("login"))
    return render_template("citizen_dashboard.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("home"))


# ---------- Officer Login ----------
@app.route("/officer_login", methods=["GET", "POST"])
def officer_login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        usr = Officer.query.filter_by(email=email).first()
        # Expect officer password to be hashed as well
        if not usr or not bcrypt.check_password_hash(usr.password, password):
            flash("Invalid credentials.", "danger")
            return redirect(url_for("officer_login"))

        session["officer_id"], session["officer_name"] = usr.id, usr.name
        flash(f"Welcome Officer {usr.name}!", "success")
        return redirect(url_for("officer_dashboard"))

    return render_template("officer_login.html")


@app.route("/officer_dashboard")
def officer_dashboard():
    if "officer_id" not in session:
        flash("Please log in first.", "warning")
        return redirect(url_for("officer_login"))
    return render_template("officer_dashboard.html")


@app.route("/officer_logout")
def officer_logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("home"))

# ---------- File a Complaint ----------
@app.route("/complaint", methods=["GET", "POST"])
def file_complaint():
    citizen = current_citizen()
    if not citizen:
        flash("Please log in first.", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        f = request.form
        title       = f.get("title", "").strip()
        location    = f.get("location", "").strip()
        category    = f.get("category", "").strip()
        subcategory = f.get("subcategory", "").strip()
        sub_subcat  = f.get("sub_subcategory", "").strip()
        priority    = f.get("priority", "Normal").strip()
        affected    = f.get("affected_people", "Just Me").strip()
        description = f.get("description", "").strip()

        if priority not in ["Normal", "Urgent", "Critical"]:
            priority = "Normal"

        # ✅ Basic validation
        if not all([title, location, category, description]):
            flash("Please fill all mandatory fields.", "danger")
            return redirect(url_for("file_complaint"))

        # ✅ Create and save complaint
        new_complaint = Complaint(
            title=title,
            location=location,
            category=category,
            subcategory=subcategory,
            sub_subcategory=sub_subcat,
            priority=priority,
            affected_people=affected,
            description=description,
            citizen_aadhar=citizen.aadhar_number,  # store aadhar
        )
        db.session.add(new_complaint)
        db.session.commit()

        # ✅ Save uploaded images (if any)
        files = request.files.getlist("images")
        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                unique_name = f"{uuid.uuid4().hex}_{filename}"
                path = os.path.join(app.config["UPLOAD_FOLDER"], unique_name)
                file.save(path)
                db.session.add(
                    ComplaintImage(complaint_id=new_complaint.id, image_path=unique_name)
                )
        db.session.commit()

        # ✅ Send confirmation email (best effort)
        try:
            msg = Message(
                subject="City Complaint Registered",
                sender=app.config['MAIL_USERNAME'],
                recipients=[citizen.email],
            )
            msg.body = (
                f"Dear {citizen.name},\n\n"
                f"Your complaint has been registered successfully in the City Complaint Portal.\n\n"
                f"Complaint No : {new_complaint.complaint_no}\n"
                f"Title        : {title}\n"
                f"Category     : {category} > {subcategory or '-'} > {sub_subcat or '-'}\n"
                f"Priority     : {priority or 'Normal'}\n"
                f"Affected     : {affected or 'Not specified'}\n"
                f"Location     : {location or 'Not specified'}\n"
                f"Description  : {description}\n\n"
                "We will notify you when the status changes.\n\n"
                "Regards,\nCity Complaint Portal"
            )
            mail.send(msg)
        except Exception:
            current_app.logger.exception("Failed to send complaint e-mail")
            flash("Complaint saved, but e-mail failed (see logs).", "warning")

        flash(f"Complaint submitted successfully. Complaint No: {new_complaint.complaint_no}", "success")
        return redirect(url_for("citizen_dashboard"))

    # GET → show form
    return render_template("complaint.html")


# ---------- Officer: Manage Complaints ----------
@app.route("/officer_complaints")
def officer_complaints():
    if "officer_id" not in session:
        flash("Please log in first.", "warning")
        return redirect(url_for("officer_login"))

    # Query complaints joined with citizen via aadhar
    rows = (
        db.session.query(
            Complaint.title,
            Complaint.location,
            Complaint.complaint_no,
            Complaint.category,
            Complaint.subcategory,
            Complaint.sub_subcategory,
            Complaint.priority,
            Complaint.affected_people,
            Complaint.description,
            Complaint.date_created,
            Complaint.status,
        )
        .join(Citizen, Citizen.aadhar_number == Complaint.citizen_aadhar)
        .order_by(Complaint.date_created.desc())
        .all()
    )
    return render_template("complaint_view.html", complaints=rows, officer_view=True)


@app.post("/solve/<complaint_no>")
def solve_complaint(complaint_no):
    # complaint_no treated as string (6-digit string)
    if "officer_id" not in session:
        flash("Please log in first.", "warning")
        return redirect(url_for("officer_login"))
    print(complaint_no)
    comp = Complaint.query.filter_by(complaint_no=complaint_no).first()
    if not comp:
        flash("Complaint not found.", "danger")
        return redirect(url_for("officer_complaints"))

    citizen = Citizen.query.filter_by(aadhar_number=comp.citizen_aadhar).first()

    if comp.status != "Solved":
        comp.status = "Solved"
        db.session.commit()
        flash(f"{complaint_no} marked as solved.", "success")

        if citizen:
            try:
                msg = Message(
                    subject="Your City Complaint has been Resolved",
                    sender=app.config['MAIL_USERNAME'],
                    recipients=[citizen.email],
                )
                msg.body = (
                    f"Dear {citizen.name},\n\n"
                    f"Your complaint has been marked as Solved.\n\n"
                    f"Complaint No : {comp.complaint_no}\n"
                    f"Category     : {comp.category}\n"
                    f"Description  : {comp.description}\n\n"
                    "If the issue still persists, please file a new complaint.\n\n"
                    "Regards,\nCity Complaint Portal"
                )
                mail.send(msg)
            except Exception:
                current_app.logger.exception("Failed to send resolved-mail")
                flash("Complaint solved, but e-mail failed (see logs).", "warning")
    else:
        flash(f"{complaint_no} is already solved.", "info")

    return redirect(url_for("officer_complaints"))

@app.route("/complaint_status", methods=["GET", "POST"])
def complaint_status():
    citizen = current_citizen()
    if not citizen:
        flash("Please log in first.", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        aadhar_no   = (request.form.get("aadhar_no") or "").strip()
        complaint_no = (request.form.get("complaint_no") or "").strip()

        if not aadhar_no or not complaint_no:
            flash("Both fields are required.", "danger")
            return redirect(url_for("complaint_status"))

        comp = Complaint.query.filter_by(
            complaint_no=complaint_no,
            citizen_aadhar=aadhar_no
        ).first()

        if not comp:
            flash("Complaint not found.", "danger")
            return redirect(url_for("complaint_status"))

        return render_template("complaint_status.html", complaint=comp)

    return render_template("complaint_status.html")

# ──────────────────── Bootstrapping ─────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
