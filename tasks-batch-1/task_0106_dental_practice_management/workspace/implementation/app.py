"""Dental Practice Management API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
(via start.sh) before every test under `--isolation per-test-server`, so there
is no carry-over state and nothing is seeded at startup.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_VALIDATION
from response import error_response

from routes.patients import bp as patients_bp
from routes.providers import bp as providers_bp
from routes.operatories import bp as operatories_bp
from routes.insurance import bp as insurance_bp
from routes.treatment_plans import bp as treatment_plans_bp
from routes.appointments import bp as appointments_bp
from routes.predeterminations import bp as predeterminations_bp
from routes.claims import bp as claims_bp
from routes.recare import bp as recare_bp
from routes.payment_plans import bp as payment_plans_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        patients_bp,
        providers_bp,
        operatories_bp,
        insurance_bp,
        treatment_plans_bp,
        appointments_bp,
        predeterminations_bp,
        claims_bp,
        recare_bp,
        payment_plans_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        # Unknown route — not a domain not-found. Use a generic 404 envelope.
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_VALIDATION, "Malformed request", 422)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_HTTP", e.description or str(e), e.code or 500)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
