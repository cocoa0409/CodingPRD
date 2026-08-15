"""Flask application entry point.

Binds 0.0.0.0:$PORT (default 10000). All state lives in in-memory dicts; a
fresh process boots with an empty store and the logical clock at
2026-08-01T00:00:00Z.
"""
import os
import threading

from flask import Flask, g

from errors import ApiError
from httpkit import error_response
from store import apply_dirty_bumps
from routes.buses import bp as buses_bp
from routes.policies_logs import bp as policies_logs_bp
from routes.workorders import bp as workorders_bp
from routes.parts import bp as parts_bp
from routes.defects import bp as defects_bp
from routes.campaigns_inspections import bp as campaigns_inspections_bp
from routes.claims import bp as claims_bp
from routes.shifts import bp as shifts_bp
from routes.mechanics_plans_ops import bp as mechanics_plans_ops_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

_lock = threading.RLock()


@app.before_request
def _acquire_lock():
    _lock.acquire()
    g.dirty = set()


@app.after_request
def _release_lock(response):
    try:
        if response.status_code < 400:
            apply_dirty_bumps()
    finally:
        _lock.release()
    return response


@app.teardown_request
def _teardown(exc):
    if _lock._is_owned():
        try:
            _lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _not_found(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _method_not_allowed(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def _unhandled(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_VALIDATION", f"Unhandled error: {e}", 400)


for bp in (buses_bp, policies_logs_bp, workorders_bp, parts_bp, defects_bp,
           campaigns_inspections_bp, claims_bp, shifts_bp,
           mechanics_plans_ops_bp):
    app.register_blueprint(bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
