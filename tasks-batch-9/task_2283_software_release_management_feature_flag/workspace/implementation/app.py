"""Software Release Management & Feature Flag Governance API.

Flat topology (no shared URL prefix), in-memory storage only, server-owned
logical clock.  Nothing is persisted and nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

HTTP_FALLBACK = {
    400: "ERR_INVALID_REQUEST",
    401: "ERR_UNAUTHENTICATED",
    403: "ERR_ROLE_NOT_PERMITTED",
    404: "ERR_RESOURCE_NOT_FOUND",
    405: "ERR_RESOURCE_NOT_FOUND",
    415: "ERR_INVALID_REQUEST",
}


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    from routes import BLUEPRINTS

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        error_id = HTTP_FALLBACK.get(status, "ERR_INVALID_REQUEST")
        return error_response(error_id, exc.description or error_id, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
