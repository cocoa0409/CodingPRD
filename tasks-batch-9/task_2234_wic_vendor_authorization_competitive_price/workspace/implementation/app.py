"""WIC Vendor Authorization & Competitive Price Management API.

In-memory only: every process start begins with an empty store and no seeded data.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        code = exc.code or 500
        if code == 404:
            return envelope.error("ERR_INVALID_REQUEST", "Unknown resource path.", 404)
        if code == 405:
            return envelope.error(
                "ERR_INVALID_REQUEST", "Method not allowed for this path.", 405
            )
        if code in (400, 415):
            return envelope.error(
                "ERR_INVALID_REQUEST", "The request payload is invalid.", 422
            )
        return envelope.error(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", code
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error", exc_info=exc)
        return envelope.error("ERR_INVALID_REQUEST", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
