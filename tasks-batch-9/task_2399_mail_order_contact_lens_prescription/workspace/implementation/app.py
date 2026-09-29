"""Mail-order contact lens prescription verification API.

Flask application factory and entrypoint.  All state lives in process memory
(see db.py); nothing is persisted and nothing is seeded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes
from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.status_code)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource does not exist.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "Method is not allowed for this path.", 405
            )
        if exc.code in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST", "Request body or query parameters are malformed.", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
