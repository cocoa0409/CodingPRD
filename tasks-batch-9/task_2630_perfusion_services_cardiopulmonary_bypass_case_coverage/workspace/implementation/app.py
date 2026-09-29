"""Perfusion Services -- Cardiopulmonary Bypass Case Coverage API.

Entry point.  Storage is in-memory only and starts completely empty on every
boot; nothing is seeded, preloaded or hardcoded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_cases
import routes_devices
import routes_incidents
import routes_master
import routes_packs
import routes_people
import routes_run
import routes_slots
from envelope import fail
from errors import ERROR_MESSAGE, ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (routes_master, routes_people, routes_devices, routes_slots,
                   routes_cases, routes_packs, routes_run, routes_incidents):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return fail(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return fail("ERR_NOT_FOUND", ERROR_MESSAGE.get("ERR_NOT_FOUND", "Not found."), 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return fail("ERR_METHOD_NOT_ALLOWED",
                    ERROR_MESSAGE.get("ERR_METHOD_NOT_ALLOWED", "Method not allowed."), 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return _not_found(exc)
        if exc.code == 405:
            return _not_allowed(exc)
        return fail("ERR_INVALID_REQUEST", exc.description or "Bad request.", exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error")
        return fail("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
