"""Errand & Task Marketplace API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding). Logical clock
defaults to 2026-01-01T00:00:00Z.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response
from routes.catalog import bp as catalog_bp
from routes.bookings import bp as bookings_bp
from routes.series import bp as series_bp
from routes.moderation import bp as moderation_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(series_bp)
    app.register_blueprint(moderation_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_NOT_FOUND", "Resource or route not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected errors as a generic 500 in the standard envelope.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
