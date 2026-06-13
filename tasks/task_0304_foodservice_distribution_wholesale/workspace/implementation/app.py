"""Foodservice Distribution & Wholesale Ordering API — Flask entry point.

In-memory only: all state lives in module-level dicts in db.py and is wiped on
every process restart. No seeding is performed at startup.
"""
import os

from flask import Flask, jsonify

import response
from errors import ApiError
from routes.catalog import bp as catalog_bp
from routes.customers import bp as customers_bp
from routes.orders import bp as orders_bp
from routes.returns import bp as returns_bp
from routes.shipments import bp as shipments_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(returns_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route — return the standard error envelope with ERR_NOT_FOUND.
        return response.error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return response.error_response(
            "ERR_NOT_FOUND", "The requested method is not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Last-resort guard: never leak a stack trace as a non-enveloped body.
        if isinstance(err, ApiError):
            return response.error_response(err.error_id, err.message, err.http_status)
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % err, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
