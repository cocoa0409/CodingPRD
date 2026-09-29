"""Insurance Market Conduct Examination API — Flask application entry point.

The whole data set lives in process memory and starts empty on every boot; the
harness relaunches this process before each test, which is the only reset needed.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import BLUEPRINTS

API_PREFIX = "/market-conduct"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        if error.code == 404:
            return error_response(
                "ERR_NOT_FOUND", "No route matches that path.", 404
            )
        if error.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "That method is not allowed on this path.",
                405,
            )
        if error.code in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 422
            )
        return error_response(
            "ERR_HTTP_ERROR", error.description or "Request failed.", error.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
