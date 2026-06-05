"""Timekeeping & FLSA Overtime API — entry point, error handling, routing.

In-memory store only; state starts empty on every boot (per-test-server
isolation). No seeding.
"""
import os

from flask import Flask, request

from errors import ApiError
from middleware import authenticate
from response import error_response

from routes.config import bp as config_bp
from routes.shifts import bp as shifts_bp
from routes.breaks import bp as breaks_bp
from routes.tips import bp as tips_bp
from routes.timesheets import bp as timesheets_bp
from routes.payroll import bp as payroll_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _authenticate():
        # Authentication (priority 1-2) runs before every business handler.
        authenticate()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(exc):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        # Surface unexpected errors as a generic invalid-request envelope so the
        # response shape stays consistent. (Re-raise ApiError handled above.)
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", str(exc), 422)

    app.register_blueprint(config_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(breaks_bp)
    app.register_blueprint(tips_bp)
    app.register_blueprint(timesheets_bp)
    app.register_blueprint(payroll_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
