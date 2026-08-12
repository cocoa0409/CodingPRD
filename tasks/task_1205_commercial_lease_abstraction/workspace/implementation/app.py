"""Entry point: Flask app, validation pipeline wiring (auth -> RBAC), error
handlers, blueprint registration. Storage is in-memory only and starts empty
on every boot."""

import os

from flask import Flask, request

from errors import ApiError, ERRORS
from middleware import authorize, current_role
from response import error_response
from routes import (
    properties, leases, schedules, recovery, reconciliations,
    critical_dates, compliance, amendments, challenges, audits,
)

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False


@app.before_request
def validation_pipeline():
    """Pipeline steps 1 (auth) and 2 (RBAC) run here for API endpoints.
    Existence (step 3) and everything after run inside the handlers, in PRD
    order."""
    if not request.path.startswith("/lease-admin"):
        return None
    rule = request.url_rule
    if rule is None:
        return None  # Let Flask's 404 handler respond.
    authorize(rule.rule)
    return None


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", str(e), 400)


for bp in (
    properties.bp, leases.bp, schedules.bp, recovery.bp,
    reconciliations.bp, critical_dates.bp, compliance.bp,
    amendments.bp, challenges.bp, audits.bp,
):
    app.register_blueprint(bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
