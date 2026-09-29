"""Glass Container Manufacturing API -- Flask application entry point.

State lives entirely in process memory (see store.py).  Nothing is persisted and
nothing is seeded: a fresh process starts with every collection empty.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_VALIDATION", "The requested path does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response(
            "ERR_VALIDATION", "The method is not allowed for the requested path.", 405
        )

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return error_response(
            "ERR_VALIDATION", "The request body could not be parsed as JSON.", 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return error_response(
                "ERR_VALIDATION", exc.description or "Request failed.", exc.code or 500
            )
        return error_response("ERR_VALIDATION", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
