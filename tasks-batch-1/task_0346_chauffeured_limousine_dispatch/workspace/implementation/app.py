"""Chauffeured Limousine Dispatch API — entry point and error handlers.

In-memory storage only (see db.py). The store starts empty on every boot; no
entity is seeded or preloaded. Re-invoking start.sh wipes all state.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes.assignments import bp as assignments_bp
from routes.config import bp as config_bp
from routes.duty import bp as duty_bp
from routes.farmouts import bp as farmouts_bp
from routes.flights import bp as flights_bp
from routes.reservations import bp as reservations_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(farmouts_bp)
    app.register_blueprint(flights_bp)
    app.register_blueprint(duty_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> ERR_NOT_FOUND envelope (PRD §5).
        return error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, HTTPException):
            return error("ERR_INVALID_REQUEST", str(exc), exc.code or 400)
        return error("ERR_INVALID_REQUEST", "Internal error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
