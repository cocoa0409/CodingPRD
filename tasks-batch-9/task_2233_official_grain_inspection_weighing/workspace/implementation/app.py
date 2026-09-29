"""Official Grain Inspection & Weighing Service — Flask application entrypoint.

State lives in process memory only (see store.py); every boot starts empty with
the logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_config
import routes_final
import routes_ops
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_config.bp)
    app.register_blueprint(routes_ops.bp)
    app.register_blueprint(routes_final.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path", 405
            )
        if exc.code and 400 <= exc.code < 500:
            return error_response(
                "ERR_INVALID_REQUEST", exc.description or "Invalid request", 422
            )
        return error_response("ERR_INTERNAL", exc.description or "Internal error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", str(exc) or "Internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
