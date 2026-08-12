"""Fair Lending Analysis & Redlining Monitoring API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import BadRequest, NotFound

from errors import ApiError, err
from response import error_resp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (
        analysis_runs, applications, board_reports, branches,
        corrective_action_plans, findings, loan_officers, markets,
        matched_pair_reviews, monitoring, peer_benchmarks, pricing_exceptions,
        remediation_payments, self_tests, underwriting_overrides,
    )

    for module in (
        markets, branches, loan_officers, applications, pricing_exceptions,
        underwriting_overrides, peer_benchmarks, analysis_runs, findings,
        matched_pair_reviews, corrective_action_plans, remediation_payments,
        self_tests, board_reports, monitoring,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_resp(e)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_resp(err("ERR_NOT_FOUND", "Resource does not exist"))

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_resp(err("ERR_NOT_FOUND", "Resource does not exist"))

    @app.errorhandler(BadRequest)
    def handle_bad_request(e):
        return error_resp(err("ERR_INVALID_REQUEST", "Malformed request"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_resp(e)
        return error_resp(ApiError("ERR_INTERNAL", 500, "Unexpected server error"))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
