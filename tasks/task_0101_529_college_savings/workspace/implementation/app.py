"""529 College Savings API — Flask entry point.

PRD: workspace/PRD.md. SCAFFOLD: SCAFFOLD.yaml.
Listens on PORT env (default 10000), binds 0.0.0.0.
"""

import os
import traceback
from flask import Flask, request, jsonify

from core.errors import APIError
from core.envelope import error_response
from core.auth import parse_auth

from routes.donors import bp as donors_bp
from routes.beneficiaries import bp as beneficiaries_bp
from routes.state_rules import bp as state_rules_bp
from routes.accounts import bp as accounts_bp
from routes.contributions import bp as contributions_bp
from routes.recurring_plans import bp as recurring_plans_bp
from routes.withdrawals import bp as withdrawals_bp
from routes.beneficiary_change_requests import bp as bcrs_bp
from routes.tax_reports import bp as tax_reports_bp
from routes.system import bp as system_bp


def _build_app() -> Flask:
    app = Flask(__name__)

    # Reject malformed JSON early but uniformly via APIError.
    app.config["TRAP_HTTP_EXCEPTIONS"] = False

    @app.before_request
    def _auth_gate():
        # Skip auth for OPTIONS/preflight.
        if request.method == "OPTIONS":
            return None
        # Skip auth for test-harness reset path (used by conftest between tests).
        if request.path.startswith("/__test__/"):
            return None
        # Apply universal auth (ERR_AUTH_MISSING / ERR_AUTH_INVALID_ROLE).
        parse_auth()
        return None

    @app.errorhandler(APIError)
    def _api_err(e):
        return error_response(e)

    @app.errorhandler(404)
    def _not_found(_e):
        return error_response(APIError("ERR_NOT_FOUND", "Resource not found", 404))

    @app.errorhandler(405)
    def _method(_e):
        return error_response(APIError("ERR_VALIDATION_FAILED", "Method not allowed", 400))

    @app.errorhandler(400)
    def _bad_req(_e):
        return error_response(APIError("ERR_VALIDATION_FAILED", "Bad request", 400))

    @app.errorhandler(Exception)
    def _unhandled(e):
        # Print to stderr so docker logs surface root cause during test runs.
        traceback.print_exc()
        if isinstance(e, APIError):
            return error_response(e)
        return error_response(APIError("ERR_VALIDATION_FAILED", str(e) or "Internal error", 400))

    # Register blueprints.
    app.register_blueprint(donors_bp)
    app.register_blueprint(beneficiaries_bp)
    app.register_blueprint(state_rules_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(contributions_bp)
    app.register_blueprint(recurring_plans_bp)
    app.register_blueprint(withdrawals_bp)
    app.register_blueprint(bcrs_bp)
    app.register_blueprint(tax_reports_bp)
    app.register_blueprint(system_bp)

    return app


app = _build_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
