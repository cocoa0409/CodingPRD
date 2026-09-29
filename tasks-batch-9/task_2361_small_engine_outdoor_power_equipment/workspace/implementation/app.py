"""Small Engine & Outdoor Power Equipment Plant API.

Flask application factory and process entry point.  All state lives in
process-local dictionaries (see store.py) and the store is EMPTY on every boot:
no entity data is ever seeded, preloaded or hardcoded.
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

    for blueprint in routes.BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not allowed for this path.",
                405,
            )
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request could not be understood.", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response(
            "ERR_INVALID_REQUEST", "Unexpected server condition: %s" % exc, 400
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
