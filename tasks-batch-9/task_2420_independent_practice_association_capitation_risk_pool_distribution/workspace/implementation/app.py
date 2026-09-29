"""IPA Capitation & Risk Pool Distribution API.

A single-process Flask application whose entire state lives in module-level
Python dictionaries (see db.py).  Nothing is persisted and nothing is seeded:
the benchmark harness relaunches this process before every test and each test
builds the state it needs through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (agreements, assignments, claims, clock, enrollees, files,
                    physicians, pools, quality, recoveries)

BLUEPRINTS = (
    clock.bp,
    agreements.bp,
    physicians.bp,
    enrollees.bp,
    assignments.bp,
    files.bp,
    pools.bp,
    claims.bp,
    recoveries.bp,
    quality.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return response.error("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed for this path.", 405)
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return response.error("ERR_INTERNAL", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - safety net
        return response.error("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
