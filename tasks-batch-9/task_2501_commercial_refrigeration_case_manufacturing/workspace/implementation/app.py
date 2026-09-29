"""Commercial Refrigeration Case Manufacturing API.

Flask application factory and process entry point.  Storage is in-memory only
and starts completely empty on every boot.
"""

import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from middleware import authenticate
from response import error
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.config["JSON_SORT_KEYS"] = False

    app.before_request(authenticate)

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return error("ERR_NOT_FOUND", "No such route", 404)
        if status == 405:
            return error("ERR_NOT_FOUND", "Method not allowed for this route", 404)
        if status == 400:
            return error("ERR_INVALID_REQUEST", "Malformed request", 400)
        return error("ERR_INTERNAL", exc.description or "Request failed", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc()
        return error("ERR_INTERNAL", "Unexpected server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
