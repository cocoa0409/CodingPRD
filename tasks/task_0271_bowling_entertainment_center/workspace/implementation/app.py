"""Bowling & Entertainment Center Booking API — Flask entry point.

In-memory storage only (see db.py). The store starts empty on every boot; no
entity is ever seeded or preloaded. Every entity is created by clients via the
declared API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

# Blueprints
from routes.catalog import bp as catalog_bp
from routes.customers import bp as customers_bp
from routes.reservations import bp as reservations_bp
from routes.lines import bp as lines_bp
from routes.leagues import bp as leagues_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(lines_bp)
    app.register_blueprint(leagues_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / resource. Use the standard error envelope.
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        if isinstance(e, HTTPException) and e.code == 400:
            return error_response("ERR_INVALID_REQUEST", 400, "Bad request")
        return error_response("ERR_INVALID_REQUEST", e.code or 500, e.description or "Error")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", 400, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
