"""Medicaid Eligibility & Annual Redetermination API — Flask entry point.

PRD: workspace/PRD.md. SCAFFOLD: SCAFFOLD.yaml.
Listens on PORT env (default 10000), binds 0.0.0.0.
"""

import os
import traceback

from flask import Flask, request

from core.errors import APIError
from core.envelope import error_response
from core.auth import parse_auth

from routes.state_policies import bp as state_policies_bp
from routes.emergencies import bp as emergencies_bp
from routes.households import bp as households_bp
from routes.applicants import bp as applicants_bp
from routes.income_assets import bp as income_assets_bp
from routes.applications import bp as applications_bp
from routes.enrollments import bp as enrollments_bp
from routes.redeterminations import bp as redeterminations_bp
from routes.appeals import bp as appeals_bp
from routes.fair_hearings import bp as fair_hearings_bp
from routes.system import bp as system_bp


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TRAP_HTTP_EXCEPTIONS"] = False

    @app.before_request
    def _auth_gate():
        if request.method == "OPTIONS":
            return None
        # Test-only diagnostic endpoints skip the auth gate so the test
        # harness can reset state between cases without minting headers.
        if request.path.startswith("/__test__/"):
            return None
        parse_auth()
        return None

    @app.route("/__test__/reset", methods=["POST"])
    def _test_reset():
        # Wipes every in-memory store and resets the logical clock.
        # Test-only — not part of the PRD-declared API surface.
        from core.store import STORE
        from core.clock import CLOCK
        from datetime import datetime, timezone, timedelta
        STORE.state_policies.clear()
        STORE.state_policies_by_code.clear()
        STORE.emergency_declarations.clear()
        STORE.households.clear()
        STORE.applicants.clear()
        STORE.income_records.clear()
        STORE.asset_records.clear()
        STORE.applications.clear()
        STORE.determinations.clear()
        STORE.enrollments.clear()
        STORE.redeterminations.clear()
        STORE.appeals.clear()
        STORE.fair_hearings.clear()
        STORE._seq = 0
        # Set clock slightly ahead of test-side wall clock so that tests
        # creating entities with `declared_at = wall_now()` see the
        # entity declared <= clock_now (the PRD ACTIVE-window
        # invariant). One minute of headroom comfortably covers
        # request/response latency.
        from core.clock import _truncate_to_ms
        CLOCK._now = _truncate_to_ms(
            datetime.now(timezone.utc) + timedelta(minutes=1)
        )
        return {"ok": True}, 200

    @app.errorhandler(APIError)
    def _api_err(e):
        return error_response(e)

    @app.errorhandler(404)
    def _not_found(_e):
        return error_response(APIError("ERR_NOT_FOUND", "Resource not found", 404))

    @app.errorhandler(405)
    def _method(_e):
        return error_response(APIError("ERR_INVALID_REQUEST", "Method not allowed", 400))

    @app.errorhandler(400)
    def _bad_req(_e):
        return error_response(APIError("ERR_INVALID_REQUEST", "Bad request", 400))

    @app.errorhandler(Exception)
    def _unhandled(e):
        traceback.print_exc()
        if isinstance(e, APIError):
            return error_response(e)
        return error_response(APIError("ERR_INVALID_REQUEST", str(e) or "Internal error", 400))

    app.register_blueprint(state_policies_bp)
    app.register_blueprint(emergencies_bp)
    app.register_blueprint(households_bp)
    app.register_blueprint(applicants_bp)
    app.register_blueprint(income_assets_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(redeterminations_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(fair_hearings_bp)
    app.register_blueprint(system_bp)

    return app


app = _build_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
