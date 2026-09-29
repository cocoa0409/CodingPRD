"""Graduate school thesis and dissertation format review & deposit API.

Boots empty on every launch: storage is process-local memory only and no entity
is ever seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "No such route on this API", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST",
                "Method not allowed for this route",
                405,
            )
        if exc.code in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST", exc.description or "Malformed request", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
