"""Fountain Beverage Service Network API.

A single-process Flask application whose entire state lives in Python dicts in
memory (see core.Store).  Nothing is seeded and nothing is persisted, so every
fresh `bash start.sh` starts from a completely empty network with the logical
clock reading 2026-08-01T00:00:00Z.
"""

import os
import sys
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_body
import routes_agreements
import routes_maintenance
import routes_outlets
import routes_routes
import routes_service
import routes_supply
import routes_units

API_PREFIX = "/fountain-network"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    for module in (
        routes_outlets,
        routes_agreements,
        routes_units,
        routes_supply,
        routes_routes,
        routes_maintenance,
        routes_service,
    ):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return error_body("ERR_INVALID_REQUEST", "No such route.", 404)
        if status == 405:
            return error_body("ERR_INVALID_REQUEST", "Method not allowed on this route.", 405)
        if status == 400:
            return error_body("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error_body("ERR_INVALID_REQUEST", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc(file=sys.stderr)
        return error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
