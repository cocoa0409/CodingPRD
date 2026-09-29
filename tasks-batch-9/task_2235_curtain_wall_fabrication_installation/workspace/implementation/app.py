"""Curtain Wall Fabrication & Installation API (task 2235).

Python + Flask, in-memory dictionary storage only.  A fresh process starts
with an empty store and the logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_core
import routes_glass
import routes_qc
import routes_zones
from envelope import fail
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_glass.bp)
    app.register_blueprint(routes_zones.bp)
    app.register_blueprint(routes_qc.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return fail(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return fail("ERR_RESOURCE_NOT_FOUND", "resource does not exist", 404)
        if exc.code == 405:
            return fail(
                "ERR_INVALID_REQUEST", "method is not allowed for this path", 405
            )
        if exc.code == 400:
            return fail(
                "ERR_INVALID_REQUEST", "required field missing or wrongly typed", 400
            )
        return fail("ERR_INVALID_REQUEST", exc.description or "request failed", exc.code)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return fail("ERR_INVALID_REQUEST", "unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
