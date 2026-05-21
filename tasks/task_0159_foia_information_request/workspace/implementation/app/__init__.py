"""FOIA Information Request API — Flask application factory."""

from flask import Flask

from .envelope import register_envelope_handlers
from .errors import register_error_handlers
from .routes.audit import audit_bp
from .routes.appeals import appeals_bp
from .routes.clock import clock_bp
from .routes.exemption_claims import exemption_claims_bp
from .routes.fee_assessments import fee_assessments_bp
from .routes.health import health_bp
from .routes.requesters import requesters_bp
from .routes.requests import requests_bp
from .routes.responsive_records import responsive_records_bp
from .routes.third_party_notices import third_party_notices_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Preserve key ordering exactly as we set it in response payloads.
    app.json.sort_keys = False

    register_envelope_handlers(app)
    register_error_handlers(app)

    app.register_blueprint(health_bp)
    app.register_blueprint(requesters_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(responsive_records_bp)
    app.register_blueprint(exemption_claims_bp)
    app.register_blueprint(third_party_notices_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(fee_assessments_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(clock_bp)

    return app
