"""HERS Home Energy Rating — code compliance verification API.

In-memory only: every process starts with a completely empty store. No data of any
kind is seeded at boot; the module encodes the system, never its contents.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_core
import routes_field
import routes_qa
import routes_ratings
import routes_sampling
from errors import ERROR_CATALOG, message_for
from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_ratings.bp)
    app.register_blueprint(routes_field.bp)
    app.register_blueprint(routes_sampling.bp)
    app.register_blueprint(routes_qa.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            error_id = "ERR_NOT_FOUND"
        elif exc.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif exc.code in (400, 415):
            error_id = "ERR_INVALID_REQUEST"
        else:
            error_id = "ERR_INTERNAL"
        status = ERROR_CATALOG.get(error_id, exc.code or 500)
        if error_id == "ERR_INVALID_REQUEST":
            return error_response(error_id, "The request body could not be parsed.", 422)
        return error_response(error_id, message_for(error_id), status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", str(exc) or message_for("ERR_INTERNAL"), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
