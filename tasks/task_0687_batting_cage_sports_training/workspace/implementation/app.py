"""Batting Cage & Sports-Training API — Flask entry point.

In-memory store, starts empty on every boot (NO seeding). Per-test-server
isolation re-launches this process before every test, wiping all state.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response
from routes.facilities import bp as facilities_bp
from routes.lanes import bp as lanes_bp
from routes.maintenance import bp as maintenance_bp
from routes.members import bp as members_bp
from routes.bookings import bp as bookings_bp
from routes.programs import bp as programs_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(facilities_bp)
    app.register_blueprint(lanes_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route path -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Never leak a stack trace; surface as a generic validation/server error.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_VALIDATION", "Unexpected error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
