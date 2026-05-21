"""Flask application factory for the IRS Installment Agreement API."""
from __future__ import annotations

from flask import Flask

from app.envelope import register_error_handlers
from app.routes.taxpayers import bp as taxpayers_bp
from app.routes.tax_liabilities import bp as tax_liabilities_bp
from app.routes.installment_agreements import bp as installment_agreements_bp
from app.routes.payments import bp as payments_bp
from app.routes.offers_in_compromise import bp as oic_bp
from app.routes.liens import bp as liens_bp
from app.routes.cnc_statuses import bp as cnc_bp
from app.routes.reconsideration_requests import bp as reconsideration_bp
from app.routes.system import bp as system_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    register_error_handlers(app)

    app.register_blueprint(taxpayers_bp)
    app.register_blueprint(tax_liabilities_bp)
    app.register_blueprint(installment_agreements_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(oic_bp)
    app.register_blueprint(liens_bp)
    app.register_blueprint(cnc_bp)
    app.register_blueprint(reconsideration_bp)
    app.register_blueprint(system_bp)

    return app
