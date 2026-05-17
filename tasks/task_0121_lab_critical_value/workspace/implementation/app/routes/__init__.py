"""Blueprint registration."""
from flask import Flask

from .patients import bp as patients_bp
from .clinicians import bp as clinicians_bp
from .test_panels import bp as test_panels_bp
from .lab_orders import bp as lab_orders_bp
from .specimens import bp as specimens_bp
from .transport_legs import bp as transport_legs_bp
from .results import bp as results_bp
from .notifications import bp as notifications_bp
from .retest_requests import bp as retest_requests_bp
from .audit_events import bp as audit_events_bp
from .test_infra import bp as test_infra_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(patients_bp)
    app.register_blueprint(clinicians_bp)
    app.register_blueprint(test_panels_bp)
    app.register_blueprint(lab_orders_bp)
    app.register_blueprint(specimens_bp)
    app.register_blueprint(transport_legs_bp)
    app.register_blueprint(results_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(retest_requests_bp)
    app.register_blueprint(audit_events_bp)
    app.register_blueprint(test_infra_bp)
