"""Fishing Charter Booking API — Flask entry point.

Boots clean (empty store) on every invocation. No seeding.
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error
from routes.infra import bp as infra_bp
from routes.charters import bp as charters_bp
from routes.crew_and_slots import bp as crew_slots_bp
from routes.bookings import bp as bookings_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(infra_bp)
    app.register_blueprint(charters_bp)
    app.register_blueprint(crew_slots_bp)
    app.register_blueprint(bookings_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> treat as a generic invalid request (no matching
        # resource path). Keep the standard envelope.
        return error("ERR_INVALID_REQUEST", "Resource or route not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        # Surface unexpected failures as a generic 400-class envelope rather
        # than Flask's HTML 500 page.
        return error("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
