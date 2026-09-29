"""Drive-Thru Speed-Of-Service API — Flask entry point.

Storage is process-local and in-memory (see db.py); every boot starts empty.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import BLUEPRINTS

API_PREFIX = "/drive-thru"


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_body("ERR_RESTAURANT_NOT_FOUND", "resource not found"), 404
        if exc.code == 405:
            return error_body("ERR_INVALID_REQUEST", "method not allowed for this path"), 400
        if exc.code in (400, 415):
            return error_body("ERR_INVALID_REQUEST", "the request could not be parsed"), 400
        if exc.code == 401:
            return error_body("ERR_UNAUTHENTICATED", "authentication headers are required"), 401
        return error_body("ERR_INVALID_REQUEST", exc.description or "request failed"), exc.code

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        return error_body("ERR_INVALID_REQUEST", "unexpected server error: %s" % exc), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
