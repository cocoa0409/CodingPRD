"""Qualified Opportunity Fund Compliance API -- Flask entry point.

Storage is in-memory only and starts completely empty on every boot: no
entity is ever seeded, preloaded or hardcoded. Tests build all state through
the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
import routes_asset
import routes_core
import routes_gain
import routes_project


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_gain.bp)
    app.register_blueprint(routes_asset.bp)
    app.register_blueprint(routes_project.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST",
                                  "No such resource path", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "Method not allowed for this path", 405)
        if exc.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST",
                                  "Malformed request body", 400)
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "Request failed",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
