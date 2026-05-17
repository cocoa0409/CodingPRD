"""Flask app factory for the Multistate Telemedicine API."""
from flask import Flask

from app.errors import ApiError, register_error_handlers
from app.routes.audit_events import bp as audit_events_bp
from app.routes.claims import bp as claims_bp
from app.routes.clock_sweep import bp as clock_sweep_bp
from app.routes.consults import bp as consults_bp
from app.routes.followups import bp as followups_bp
from app.routes.invoices import bp as invoices_bp
from app.routes.patients import bp as patients_bp
from app.routes.physicians import bp as physicians_bp
from app.routes.prescriptions import bp as prescriptions_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Preserve route handler error semantics: do not swap 404/405 for HTMLs.
    app.url_map.strict_slashes = False

    register_error_handlers(app)

    app.register_blueprint(physicians_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(consults_bp)
    app.register_blueprint(prescriptions_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(followups_bp)
    app.register_blueprint(audit_events_bp)
    app.register_blueprint(clock_sweep_bp)

    return app
