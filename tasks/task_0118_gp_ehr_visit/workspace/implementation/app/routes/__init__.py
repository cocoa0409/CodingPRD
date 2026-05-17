"""Blueprint registration."""
from flask import Flask

from .patients import bp as patients_bp
from .providers import bp as providers_bp
from .encounters import bp as encounters_bp
from .cpt_codes import bp as cpt_codes_bp
from .prescriptions import bp as prescriptions_bp
from .referrals import bp as referrals_bp
from .portal import bp as portal_bp
from .hedis_routes import bp as hedis_bp
from .audit_routes import bp as audit_bp
from .test_infra import bp as test_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(patients_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(encounters_bp)
    app.register_blueprint(cpt_codes_bp)
    app.register_blueprint(prescriptions_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(hedis_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(test_bp)
