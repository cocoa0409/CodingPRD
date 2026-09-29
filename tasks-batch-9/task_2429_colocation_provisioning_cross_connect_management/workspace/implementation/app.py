"""Colocation Provisioning & Cross-Connect Management — Flask application.

Every entity lives in memory only (see store.py) and the store is empty on
every boot: nothing is seeded, preloaded or hardcoded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.connect import bp as connect_bp
from routes.contracts import bp as contracts_bp
from routes.core import bp as core_bp
from routes.facility import bp as facility_bp
from routes.ops import bp as ops_bp
from routes.power import bp as power_bp

PREFIX = "/colocation"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (core_bp, contracts_bp, facility_bp, power_bp, connect_bp, ops_bp):
        app.register_blueprint(blueprint, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "no such route", 404)
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "method not allowed for this route", 405
            )
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "malformed request", 400)
        return error_response(
            "ERR_INTERNAL", exc.description or "request failed", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
