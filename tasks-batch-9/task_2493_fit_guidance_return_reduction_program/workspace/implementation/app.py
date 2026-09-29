"""Fit Guidance & Return Reduction Program — application entry point.

Storage is in-memory only and starts completely empty on every boot: no seed
data, no fixtures, no persistence of any kind.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    # the envelope and every row must keep their declared field order
    app.json.sort_keys = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
        elif status == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif status == 500:
            error_id = "ERR_INTERNAL"
        else:
            error_id = "ERR_INVALID_REQUEST"
        return error_response(error_id, exc.description or exc.name, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", str(exc) or "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
