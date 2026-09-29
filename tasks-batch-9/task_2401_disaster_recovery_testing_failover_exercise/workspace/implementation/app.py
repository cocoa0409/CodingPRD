"""Disaster Recovery Testing & Failover Exercise API.

A single Flask process holding every entity in plain Python dictionaries.  The
store is EMPTY at boot: no seeding, no preloading, no fixtures.  The harness
restarts this process before every individual test, so a fresh boot is always a
blank slate with the logical clock reading 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
import routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_NOT_FOUND", "No such resource.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error("ERR_METHOD_NOT_ALLOWED",
                     "The method is not allowed for this path.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        # A malformed body reaches us as a 400 BadRequest from werkzeug.
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                     exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error("ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
