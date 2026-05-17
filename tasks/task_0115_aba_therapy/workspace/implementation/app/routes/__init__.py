"""Blueprint registration."""
from flask import Flask

from .authorizations import bp as authorizations_bp
from .claims import bp as claims_bp
from .clinics import bp as clinics_bp
from .clock import bp as clock_bp
from .evaluations import bp as evaluations_bp
from .patients import bp as patients_bp
from .sessions import bp as sessions_bp
from .therapists import bp as therapists_bp
from .treatment_plans import bp as plans_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(clock_bp)
    app.register_blueprint(clinics_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(therapists_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(authorizations_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(claims_bp)
