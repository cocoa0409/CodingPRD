"""Corporate Fitness Center Management API — Flask entry point.

Storage is a process-local in-memory dictionary store (see core.Store). Nothing
is seeded, nothing is persisted: every `start.sh` invocation begins with an
empty database and the logical clock pinned at 2026-08-01T00:00:00Z.
"""
import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import core
from core import ApiError, error_response, new_request_id

import r_assign
import r_contracts
import r_facility
import r_incidents
import r_invoices
import r_members
import r_ops
import r_programs
import r_reads
import r_staff

_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    for module in (r_contracts, r_staff, r_facility, r_programs, r_assign, r_members,
                   r_incidents, r_invoices, r_ops, r_reads):
        app.register_blueprint(module.bp)

    @app.before_request
    def _before():
        _LOCK.acquire()
        g.lock_held = True
        g.request_id = new_request_id()

    @app.teardown_request
    def _teardown(exc):
        if getattr(g, "lock_held", False):
            g.lock_held = False
            try:
                _LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        status = err.code or 500
        if status == 404:
            return error_response("ERR_INVALID_REQUEST", 404, "resource not found")
        if status == 405:
            return error_response("ERR_INVALID_REQUEST", 405, "method not allowed")
        if status == 400:
            return error_response("ERR_INVALID_REQUEST", 400, "malformed request")
        return error_response("ERR_INVALID_REQUEST", status, err.description or "error")

    @app.errorhandler(Exception)
    def _unhandled(err):
        return error_response("ERR_INVALID_REQUEST", 500, str(err))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
