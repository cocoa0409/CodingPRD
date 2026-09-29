"""Tip Pooling, Tip Credit and Service Charge Distribution API.

A single Flask process holding all state in memory.  Nothing is seeded: the
store is completely empty on every boot and every row arrives through the
documented endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_config
import routes_disputes
import routes_periods
import routes_pools
import routes_shifts
from envelope import error_response
from errors import ApiError
from store import begin_request


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_config.bp)
    app.register_blueprint(routes_periods.bp)
    app.register_blueprint(routes_shifts.bp)
    app.register_blueprint(routes_pools.bp)
    app.register_blueprint(routes_disputes.bp)

    @app.before_request
    def _start_request():
        begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 401:
            return error_response(
                "ERR_UNAUTHENTICATED", "Authentication headers are required.", 401
            )
        if exc.code == 403:
            return error_response("ERR_FORBIDDEN_ROLE", "Role not authorised.", 403)
        if exc.code in (404, 405):
            return error_response(
                "ERR_RECORD_NOT_FOUND", "No such resource or route.", 404
            )
        if exc.code == 415:
            return error_response(
                "ERR_INVALID_REQUEST", "Request body must be JSON.", 400
            )
        if exc.code and exc.code < 500:
            return error_response(
                "ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400
            )
        return error_response("ERR_INVALID_REQUEST", "Unhandled server error.", 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        import traceback

        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "Unhandled server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
