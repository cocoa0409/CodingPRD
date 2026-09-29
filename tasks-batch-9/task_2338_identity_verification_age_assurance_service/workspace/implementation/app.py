"""Identity Verification & Age Assurance API.

A single Flask process holding all state in memory. Every start is a cold start: the
store is empty and nothing is ever seeded, preloaded or hardcoded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        if exc.code == 404:
            return response.error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return response.error_response("ERR_METHOD_NOT_ALLOWED",
                                           "Method not allowed for this resource.", 405)
        if exc.code == 400:
            return response.error_response("ERR_INVALID_REQUEST",
                                           "Request body failed schema validation.", 422)
        if exc.code == 415:
            return response.error_response("ERR_INVALID_REQUEST",
                                           "Request body failed schema validation.", 422)
        return response.error_response("ERR_INTERNAL", exc.description or "Internal server error.",
                                       exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", exc)
        return response.error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
