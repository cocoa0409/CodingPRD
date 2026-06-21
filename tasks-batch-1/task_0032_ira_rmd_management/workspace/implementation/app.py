"""Entry point for the IRA & RMD Management API.

The store starts empty on every boot. The per-test-server harness restarts this
process before every test, so no carry-over state survives across runs.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError
from response import error_response
from routes import (
    accounts,
    audit_events,
    beneficiaries,
    contributions,
    conversions,
    distributions,
    forms_1099r,
    owners,
    rmd_schedules,
    system,
)


def create_app():
    app = Flask(__name__)

    app.register_blueprint(owners.bp)
    app.register_blueprint(accounts.bp)
    app.register_blueprint(contributions.bp)
    app.register_blueprint(distributions.bp)
    app.register_blueprint(conversions.bp)
    app.register_blueprint(beneficiaries.bp)
    app.register_blueprint(rmd_schedules.bp)
    app.register_blueprint(forms_1099r.bp)
    app.register_blueprint(audit_events.bp)
    app.register_blueprint(system.bp)

    @app.errorhandler(APIError)
    def handle_api_error(exc: APIError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_):
        # Routes that do not exist at all (vs. an entity-not-found inside a route).
        return error_response("ERR_NOT_FOUND", "Route not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed for this route.", 400)

    @app.errorhandler(400)
    def handle_400(_):
        return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exc(exc: HTTPException):
        # Generic fallback for any other werkzeug HTTPException; map to a sensible code.
        status = exc.code or 500
        if status == 401:
            return error_response("ERR_MISSING_AUTH", exc.description or "Auth required.", 401)
        if status == 403:
            return error_response("ERR_UNAUTHORIZED", exc.description or "Forbidden.", 403)
        if status == 404:
            return error_response("ERR_NOT_FOUND", exc.description or "Not found.", 404)
        if status == 409:
            return error_response("ERR_INVALID_STATE", exc.description or "Conflict.", 409)
        if status == 412:
            return error_response("ERR_STALE_VERSION", exc.description or "Stale version.", 412)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Bad request.", 400 if status < 500 else 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        # Last-resort safety net so the server never returns a non-envelope 500.
        return error_response("ERR_INVALID_REQUEST", f"Unexpected server error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
