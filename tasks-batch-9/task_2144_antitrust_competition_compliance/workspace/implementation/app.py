"""Antitrust & Competition Compliance API — entry point.

Storage is entirely in-memory and starts EMPTY on every boot. Nothing is
seeded, preloaded or hardcoded; every entity is created by clients through
the declared endpoints.
"""
import os

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

import domain
from envelope import error_response
from errors import ApiError, ERROR_STATUS
from ladder import ROLES, commit
from store import db

import routes_core
import routes_assoc
import routes_biz
import routes_ops


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_assoc.bp)
    app.register_blueprint(routes_biz.bp)
    app.register_blueprint(routes_ops.bp)

    @app.before_request
    def _acquire():
        db.lock.acquire()
        g._locked = True
        g._dirty = []
        role = request.headers.get("X-User-Role")
        user_id = request.headers.get("X-User-ID")
        if user_id and role in ROLES:
            # Lazy, time-gated transitions are evaluated at the start of every
            # request that reads or validates the affected rows (PRD 2.4).
            domain.sweep()
            commit()

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_locked", False):
            g._locked = False
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 405:
            return error_response("ERR_INVALID_REQUEST", "method not allowed", 405)
        if err.code == 404:
            return error_response("ERR_INVALID_REQUEST", "resource not found", 404)
        if err.code == 400:
            return error_response("ERR_INVALID_REQUEST", "malformed request", 400)
        return error_response("ERR_INVALID_REQUEST", err.description or "request failed",
                              err.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(err):
        return error_response("ERR_INVALID_REQUEST", "unexpected server error: %s" % err, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
