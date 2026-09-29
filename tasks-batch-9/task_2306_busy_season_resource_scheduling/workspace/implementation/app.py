"""Busy Season Resource Scheduling API.

Python + Flask, storage entirely in memory.  The process starts with every
entity table empty and the logical clock at 2026-08-01T00:00:00Z; nothing is
seeded, preloaded or read from disk.
"""

import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import assignments, compliance, engagements, phases, reference

# One request at a time: every write touches several derived rows, and the
# scaffold's concurrency rules are expressed as optimistic version checks on a
# strictly sequential request stream.
_lock = threading.RLock()

API_PREFIX = "/scheduling"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference.bp, url_prefix=API_PREFIX)
    app.register_blueprint(engagements.bp, url_prefix=API_PREFIX)
    app.register_blueprint(phases.bp, url_prefix=API_PREFIX)
    app.register_blueprint(assignments.bp, url_prefix=API_PREFIX)
    app.register_blueprint(compliance.bp, url_prefix=API_PREFIX)

    @app.before_request
    def _begin():
        _lock.acquire()
        g.lock_held = True
        g.marks = {}
        g.created = set()

    @app.teardown_request
    def _end(_exception=None):
        if g.pop("lock_held", False):
            try:
                _lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        g.marks = {}
        return response.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        g.marks = {}
        return response.error_response(
            "ERR_INVALID_REQUEST", err.description or err.name, err.code or 500
        )

    @app.errorhandler(Exception)
    def _unhandled(err):  # pragma: no cover - safety net
        g.marks = {}
        return response.error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
