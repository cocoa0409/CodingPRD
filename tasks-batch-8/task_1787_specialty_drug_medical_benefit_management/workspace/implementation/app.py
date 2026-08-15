"""Specialty Drug Medical-Benefit Management API — Flask entry point.

In-memory only; the store starts empty on every boot (per-test-server
isolation: the harness kills and re-launches via start.sh before each test).
A global re-entrant lock serializes request handling so every mutation and
its cascades commit atomically within the request (PRD 2).
"""
import os
import threading

from flask import Flask, g

from errors import ApiError
from response import error_response
from services.sweep import run_sweep

_REQUEST_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:
        app.config["JSON_SORT_KEYS"] = False

    from routes import (
        drugs, asp_schedules, clinical_policies, provider_accounts,
        authorizations, claims, adjustments, redirections,
        biosimilar_policies, pipeline, clock,
    )
    for mod in (
        drugs, asp_schedules, clinical_policies, provider_accounts,
        authorizations, claims, adjustments, redirections,
        biosimilar_policies, pipeline, clock,
    ):
        app.register_blueprint(mod.bp)

    @app.before_request
    def _begin_request():
        _REQUEST_LOCK.acquire()
        g._lock_held = True
        try:
            # lazy application of clock-due transitions, before any endpoint's
            # precondition checks read time-sensitive entities (PRD 2.4)
            run_sweep()
        except Exception:
            _REQUEST_LOCK.release()
            g._lock_held = False
            raise

    @app.teardown_request
    def _end_request(exc):
        if getattr(g, "_lock_held", False):
            g._lock_held = False
            _REQUEST_LOCK.release()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        import traceback
        traceback.print_exc()
        return error_response("ERR_INTERNAL", f"unexpected error: {err}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
