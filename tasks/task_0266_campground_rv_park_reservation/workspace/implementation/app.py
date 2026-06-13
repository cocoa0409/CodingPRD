"""Campground & RV Park Reservation API — Flask entry point.

In-memory only. No seeding. Boots empty on every process start.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.parks import bp as parks_bp
from routes.sites import bp as sites_bp
from routes.guests import bp as guests_bp
from routes.reservations import bp as reservations_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(parks_bp)
    app.register_blueprint(sites_bp)
    app.register_blueprint(guests_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
