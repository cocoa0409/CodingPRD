"""Grocery Online Ordering & Fulfillment API — Flask entry point.

In-memory storage only (db.py module-level dicts). Nothing is seeded at
startup; every entity is created by tests through the declared API surface.
A fresh process (start.sh re-invocation) yields a clean store.
"""
import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.stores import bp as stores_bp
from routes.customers import bp as customers_bp
from routes.pickers import bp as pickers_bp
from routes.products import bp as products_bp
from routes.slots import bp as slots_bp
from routes.orders import bp as orders_bp
from routes.order_lines import bp as order_lines_bp
from routes.substitutions import bp as substitutions_bp
from routes.payments import bp as payments_bp
from routes.age_checks import bp as age_checks_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(stores_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(pickers_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(slots_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(order_lines_bp)
    app.register_blueprint(substitutions_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(age_checks_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / path -> generic validation-shaped 404 envelope.
        return error_response("ERR_VALIDATION", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_VALIDATION", "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        if isinstance(e, HTTPException):
            return error_response("ERR_VALIDATION", e.description or "Request error", e.code or 400)
        return error_response("ERR_VALIDATION", "Internal error: %s" % str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
