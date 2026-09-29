"""Greenhouse vegetable production API.

Storage is in-process memory only: every start.sh invocation begins with a
completely empty dataset and a logical clock parked at 2026-08-01T00:00:00Z.
Nothing is seeded, nothing is persisted, nothing is read from disk.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import store
from envelope import error_response
from errors import ApiError
from routes import (climate, clock, commerce, cycles, fertigation, ipm, labor,
                    lots, zones)

BLUEPRINTS = (
    zones.bp,
    cycles.bp,
    climate.bp,
    fertigation.bp,
    ipm.bp,
    labor.bp,
    lots.bp,
    commerce.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    # A fresh process starts from a clean slate.
    store.reset()
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND", "Resource not found"))
        if err.code == 405:
            return error_response(
                ApiError("ERR_NOT_FOUND", "Method not allowed for this path", 405)
            )
        if err.code and 400 <= err.code < 500:
            return error_response(
                ApiError("ERR_VALIDATION", err.description or "Bad request")
            )
        return error_response(
            ApiError("ERR_INTERNAL", err.description or "Internal error", 500)
        )

    @app.errorhandler(Exception)
    def _unhandled(err):  # pragma: no cover - defensive
        return error_response(ApiError("ERR_INTERNAL", str(err) or "Internal error", 500))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
