"""Audience measurement panel operations API — entry point.

The store is entirely in memory and starts empty on every boot: no seeding,
no preloading, no persistence. Every entity is created by clients through the
declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ERROR_STATUS, ApiError
from response import error_body
from routes_client import bp as client_bp
from routes_core import bp as core_bp
from routes_governance import bp as governance_bp
from routes_household import bp as household_bp
from routes_meter import bp as meter_bp
from routes_reference import bp as reference_bp
from routes_run import bp as run_bp


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    app.register_blueprint(core_bp)
    app.register_blueprint(reference_bp)
    app.register_blueprint(household_bp)
    app.register_blueprint(meter_bp)
    app.register_blueprint(run_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(governance_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_body("ERR_NOT_FOUND", "resource not found", 404)
        if exc.code == 405:
            return error_body("ERR_METHOD_NOT_ALLOWED",
                              "method not allowed for this path", 405)
        if exc.code in (400, 415):
            return error_body("ERR_INVALID_REQUEST",
                              exc.description or "invalid request", 422)
        return error_body("ERR_INVALID_REQUEST",
                          exc.description or "request failed", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", "unexpected server error: %s" % exc,
                          500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False)
