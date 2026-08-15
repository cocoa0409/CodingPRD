"""Insurance Rate Filing & State Approval API — entry point.

In-memory Flask server. The store starts empty on every boot; the logical
clock starts at exactly 2026-08-01T00:00:00Z and advances only via
POST /_clock/set_current_utc.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from routes import calendar, core, filings, indications, objections, waves


def create_app():
    app = Flask(__name__)

    app.register_blueprint(core.bp)
    app.register_blueprint(indications.bp)
    app.register_blueprint(filings.bp)
    app.register_blueprint(objections.bp)
    app.register_blueprint(waves.bp)
    app.register_blueprint(calendar.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response(ApiError(ERR_NOT_FOUND, "Resource not found", 404))

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response(ApiError(ERR_NOT_FOUND, "Resource not found", 404))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return error_response(
                ApiError(ERR_INVALID_REQUEST, e.description or "Bad request", e.code)
                if e.code and 400 <= e.code < 500
                else ApiError(ERR_INVALID_REQUEST, "Bad request", 400)
            )
        app.logger.exception("unexpected error")
        return error_response(ApiError(ERR_INVALID_REQUEST, "Internal error", 400))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
