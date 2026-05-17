"""Blueprint registration."""
from flask import Flask

from .therapists import bp as therapists_bp
from .licenses import bp as licenses_bp
from .supervisors import bp as supervisors_bp
from .supervision_assignments import bp as supervision_assignments_bp
from .patients import bp as patients_bp
from .insurance_plans import bp as insurance_plans_bp
from .appointments import bp as appointments_bp
from .sessions import bp as sessions_bp
from .claims import bp as claims_bp
from .crisis_assessments import bp as crisis_bp
from .safety_plans import bp as safety_plans_bp
from .clock_routes import bp as clock_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(therapists_bp)
    app.register_blueprint(licenses_bp)
    app.register_blueprint(supervisors_bp)
    app.register_blueprint(supervision_assignments_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(insurance_plans_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(crisis_bp)
    app.register_blueprint(safety_plans_bp)
    app.register_blueprint(clock_bp)
