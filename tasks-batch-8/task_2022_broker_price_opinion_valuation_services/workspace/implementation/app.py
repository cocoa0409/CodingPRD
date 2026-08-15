"""Broker Price Opinion & Valuation Services API — Flask entry point."""

import os
import traceback

from flask import Flask

import db
from errors import ApiError, ERR_NOT_FOUND
from response import error_response

from routes.client_accounts import bp as client_accounts_bp
from routes.state_regulations import bp as state_regulations_bp
from routes.properties import bp as properties_bp
from routes.brokers import bp as brokers_bp
from routes.orders import bp as orders_bp
from routes.comparables import bp as comparables_bp
from routes.photos import bp as photos_bp
from routes.fee_lines import bp as fee_lines_bp
from routes.qc import bp as qc_bp
from routes.payouts import bp as payouts_bp
from routes.forecasts import bp as forecasts_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    db.init_store()

    for blueprint in (
        client_accounts_bp,
        state_regulations_bp,
        properties_bp,
        brokers_bp,
        orders_bp,
        comparables_bp,
        photos_bp,
        fee_lines_bp,
        qc_bp,
        payouts_bp,
        forecasts_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", f"Unexpected error: {err}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
