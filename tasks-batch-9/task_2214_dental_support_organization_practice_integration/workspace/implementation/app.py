"""Flask entry point for the DSO practice-integration API.

Storage is process-local and in-memory only; a fresh process starts with every
collection empty, so nothing is seeded at boot.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import config
import response
import routes
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in routes.BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=config.API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return response.error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "The method is not allowed for this resource.",
                405,
            )
        if exc.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request payload is invalid.", 400
            )
        return response.error_response(
            "ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        app.logger.exception("unhandled error")
        return response.error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
