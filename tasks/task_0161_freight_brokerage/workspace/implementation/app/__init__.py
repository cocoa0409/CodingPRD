"""Freight Brokerage API — Flask application factory."""

from flask import Flask

from .errors import register_error_handlers
from .routes.brokerages import brokerages_bp
from .routes.shippers import shippers_bp
from .routes.carriers import carriers_bp
from .routes.rate_contracts import rate_contracts_bp
from .routes.quote_requests import quote_requests_bp
from .routes.loads import loads_bp
from .routes.accessorials import accessorials_bp
from .routes.invoices import invoices_bp
from .routes.dispute_claims import dispute_claims_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False

    register_error_handlers(app)

    app.register_blueprint(brokerages_bp)
    app.register_blueprint(shippers_bp)
    app.register_blueprint(carriers_bp)
    app.register_blueprint(rate_contracts_bp)
    app.register_blueprint(quote_requests_bp)
    app.register_blueprint(loads_bp)
    app.register_blueprint(accessorials_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(dispute_claims_bp)

    return app
