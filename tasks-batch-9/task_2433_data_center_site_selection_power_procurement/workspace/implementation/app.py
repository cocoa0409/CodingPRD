"""Application entry point.

A single foreground Flask process. All state is in-memory and empty on boot:
nothing is seeded, preloaded or read from disk.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from api import bp
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return response.error(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not allowed for this resource.",
                405,
            )
        if exc.code in (400, 415):
            return response.error(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 422
            )
        return response.error("ERR_INTERNAL", exc.description or "Error", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
