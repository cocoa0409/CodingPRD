"""Excise Tax Filing & Compliance API — Flask entry point.

In-memory only: all state lives in module-level dicts inside store.py and is
empty at every process boot. The logical clock starts at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

import errors
from errors import ApiError
from response import error_response
from auth import current_user

app = Flask(__name__)

from routes.config import bp as config_bp
from routes.registrants import bp as registrants_bp
from routes.compliance import bp as compliance_bp
from routes.events import bp as events_bp
from routes.returns import bp as returns_bp
from routes.claims import bp as claims_bp
from routes.audit import bp as audit_bp

for bp in (config_bp, registrants_bp, compliance_bp, events_bp, returns_bp,
           claims_bp, audit_bp):
    app.register_blueprint(bp)


@app.before_request
def _auth_gate():
    # Priority 1: X-User-ID / X-User-Role presence and validity, on every route.
    current_user()


@app.errorhandler(ApiError)
def _api_error(exc):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def _not_found(_exc):
    return error_response(errors.ERR_NOT_FOUND[0], 404, "Resource not found")


@app.errorhandler(405)
def _method_not_allowed(_exc):
    return error_response(errors.ERR_NOT_FOUND[0], 404, "Resource not found")


@app.errorhandler(Exception)
def _unhandled(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.http_status, exc.message)
    app.logger.exception("unhandled error")
    return error_response("ERR_INTERNAL", 500, str(exc))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
