"""Community Resource Directory API — Flask entry point.

Boots empty every time (no seeding). Registers all route modules and installs
a single error handler that emits the standard envelope for both ApiError and
uncaught 4xx/500s.
"""
import os
import sys
import traceback

from flask import Flask, request

# Make sibling modules importable even when the file is launched directly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response
import routes as routes_pkg


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    # Preserve declaration order in dict responses.
    app.json.sort_keys = False

    routes_pkg.register_all(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _handle_404(_):
        # Unknown path — treat as "invalid request". Tests hit known paths only.
        return error_response(ERR_INVALID_REQUEST, "not found", 404)

    @app.errorhandler(405)
    def _handle_405(_):
        return error_response(ERR_INVALID_REQUEST, "method not allowed", 405)

    @app.errorhandler(400)
    def _handle_400(_):
        return error_response(ERR_INVALID_REQUEST, "bad request", 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        # Log to stderr; do NOT leak internals in the response body.
        traceback.print_exc()
        return error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
