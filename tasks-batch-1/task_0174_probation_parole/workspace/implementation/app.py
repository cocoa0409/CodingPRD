"""Probation & Parole Case Management API — Flask entry point.

Storage is fully in-memory (see db.py); the store starts EMPTY on every boot.
Nothing is seeded or preloaded. start.sh reads $PORT (default 10000) and binds
0.0.0.0 in the foreground.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.officers import bp as officers_bp
from routes.supervisees import bp as supervisees_bp
from routes.risk_assessments import bp as risk_bp
from routes.conditions import bp as conditions_bp
from routes.check_ins import bp as checkins_bp
from routes.drug_tests import bp as drugtests_bp
from routes.violations import bp as violations_bp
from routes.sanctions import bp as sanctions_bp
from routes.obligations import bp as obligations_bp
from routes.payments import bp as payments_bp
from routes.court_reports import bp as courtreports_bp
from routes.transfers import bp as transfers_bp
from routes.early_terminations import bp as earlyterm_bp
from routes.flat import bp as flat_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        officers_bp,
        supervisees_bp,
        risk_bp,
        conditions_bp,
        checkins_bp,
        drugtests_bp,
        violations_bp,
        sanctions_bp,
        obligations_bp,
        payments_bp,
        courtreports_bp,
        transfers_bp,
        earlyterm_bp,
        flat_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_INVALID_REQUEST", str(e), e.code or 400)
        return error_response("ERR_INVALID_REQUEST", "Internal error.", 400)

    @app.after_request
    def _close_connection(response):
        # Transport hygiene only: the per-test-server harness reuses a pooled
        # keep-alive client socket across the threaded Werkzeug dev server's
        # connection teardown, which can intermittently surface as a
        # BadStatusLine / ConnectionError race. Forcing Connection: close
        # prevents socket reuse. No endpoint, field, status code, error_id,
        # state transition, or calculation is affected.
        response.headers["Connection"] = "close"
        return response

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
