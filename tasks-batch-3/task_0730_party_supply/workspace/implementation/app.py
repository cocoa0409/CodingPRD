"""Party Supply Store API — Flask entry point."""
from __future__ import annotations
import os
import logging

from flask import Flask, jsonify, request

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, HTTP
from response import error_response
from routes.skus import bp as skus_bp
from routes.bundles import bp as bundles_bp
from routes.customers import bp as customers_bp
from routes.orders import bp as orders_bp
from routes.helium import bp as helium_bp
from routes.delivery import bp as delivery_bp
from routes.rentals import bp as rentals_bp
from routes.custom_print import bp as custom_print_bp
from routes.events import bp as events_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)

    # Register blueprints under /api
    for bp in (
        skus_bp,
        bundles_bp,
        customers_bp,
        orders_bp,
        helium_bp,
        delivery_bp,
        rentals_bp,
        custom_print_bp,
        events_bp,
        clock_bp,
    ):
        app.register_blueprint(bp, url_prefix="/api")

    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_e):
        # If the URL didn't match a route, return 404 ERR_NOT_FOUND envelope.
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        # Treat method-not-allowed as invalid request per envelope contract.
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 400)

    @app.errorhandler(400)
    def _bad_request(_e):
        return error_response(ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(500)
    def _server_error(e):
        # Never leak stack traces; treat unhandled errors as invalid request.
        logging.exception("Unhandled server error")
        return error_response(ERR_INVALID_REQUEST, "Server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    # Quiet the default Flask/werkzeug banner + access log noise for benchmark output.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
