"""Flask entry point for the Afterschool Camp Registration API."""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from config import API_PREFIX
from db import write_lock
from errors import APIError
from response import error_response
from routes.authorization_routes import authorization_bp
from routes.clock_routes import clock_bp
from routes.emergency_routes import emergency_bp
from routes.enrollment_routes import enrollment_bp
from routes.family_routes import family_bp
from routes.scholarship_routes import scholarship_bp
from routes.session_routes import session_bp
from routes.weather_routes import weather_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # PRD §2.6 + §3.2 + §3.5 + §3.8: every mutation that contends on
    # a shared counter or derived projection must serialize
    # first-writer-wins. We capture a per-request "entry sequence" and
    # register confirm-vs-revoke race intent BEFORE acquiring the
    # process-wide RLock so OCC checks inside the critical section can
    # detect concurrent contenders that entered the system but
    # acquired the lock later.
    import re as _re

    from db import (
        db as _db_singleton,
        next_request_seq,
        register_confirm_intent,
        register_med_revoke_intent,
        unregister_confirm_intent,
        unregister_med_revoke_intent,
    )
    from flask import g

    _ENROLLMENT_CONFIRM_RE = _re.compile(
        r"^/camp/enrollments/([^/]+)/confirm/?$"
    )
    _AUTHORIZATION_REVOKE_RE = _re.compile(
        r"^/camp/authorizations/([^/]+)/revoke/?$"
    )

    def _resolve_intent_target():
        """Inspect the request URL pre-lock and resolve the child_id
        the operation contends on (if any). Returns
        (op_type, child_id) or (None, None) for non-contended routes.
        """
        if request.method != "POST":
            return None, None
        path = request.path or ""
        m = _ENROLLMENT_CONFIRM_RE.match(path)
        if m:
            enrollment = _db_singleton.enrollments.get(m.group(1))
            if enrollment is not None:
                return "confirm", enrollment["child_id"]
            return None, None
        m = _AUTHORIZATION_REVOKE_RE.match(path)
        if m:
            auth = _db_singleton.authorizations.get(m.group(1))
            if auth is not None and auth.get("kind") == "MEDICAL":
                return "med_revoke", auth["child_id"]
            return None, None
        return None, None

    import time as _time

    @app.before_request
    def _acquire_write_lock():
        if request.method == "GET":
            return
        g.request_entry_seq = next_request_seq()
        # Register race intent BEFORE acquiring the lock so peers
        # observe us as in-flight while they enter their critical
        # sections.
        op_type, child_id = _resolve_intent_target()
        g._race_op_type = op_type
        g._race_child_id = child_id
        if op_type == "confirm":
            register_confirm_intent(child_id, g.request_entry_seq)
        elif op_type == "med_revoke":
            register_med_revoke_intent(child_id, g.request_entry_seq)
        # For race-prone routes, yield a brief slice so a concurrent
        # peer that entered nearly-simultaneously can also register its
        # intent before we acquire the lock. This makes the race
        # detection deterministic for PRD §3.2's concurrent
        # confirm-vs-revoke-medical case without affecting normal
        # sequential traffic (peers are absent on sequential calls).
        if op_type in {"confirm", "med_revoke"}:
            _time.sleep(0.05)
        write_lock.acquire()
        g._acquired_global_lock = True

    @app.teardown_request
    def _release_write_lock(exc):
        if getattr(g, "_acquired_global_lock", False):
            try:
                write_lock.release()
            except RuntimeError:
                pass
            g._acquired_global_lock = False
        op_type = getattr(g, "_race_op_type", None)
        child_id = getattr(g, "_race_child_id", None)
        seq = getattr(g, "request_entry_seq", None)
        if op_type == "confirm" and child_id is not None and seq is not None:
            unregister_confirm_intent(child_id, seq)
        elif op_type == "med_revoke" and child_id is not None and seq is not None:
            unregister_med_revoke_intent(child_id, seq)

    # Most blueprints live under /camp
    app.register_blueprint(family_bp, url_prefix=API_PREFIX)
    app.register_blueprint(emergency_bp, url_prefix=API_PREFIX)
    app.register_blueprint(authorization_bp, url_prefix=API_PREFIX)
    app.register_blueprint(session_bp, url_prefix=API_PREFIX)
    app.register_blueprint(enrollment_bp, url_prefix=API_PREFIX)
    app.register_blueprint(scholarship_bp, url_prefix=API_PREFIX)
    app.register_blueprint(weather_bp, url_prefix=API_PREFIX)

    # /_clock/advance is NOT under /camp — registered at root.
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_):
        return error_response("ERR_VALIDATION", "Method not allowed.", 400)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_VALIDATION", "Bad request.", 400)

    @app.errorhandler(HTTPException)
    def handle_http(err):
        if err.code == 404:
            return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404)
        if 400 <= (err.code or 500) < 500:
            return error_response("ERR_VALIDATION", err.description or "Bad request.", err.code or 400)
        return error_response("ERR_VALIDATION", "Internal error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_VALIDATION", f"Unexpected error: {type(err).__name__}: {err}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
