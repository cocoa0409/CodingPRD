"""RIA Practice API — entry point, error handling, blueprint registration.

In-memory only. No data is seeded, preloaded, or persisted; the store starts
empty on every fresh boot. The test harness relaunches this process before each
test, so every test sees a clean store.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.fee_schedules import bp as fee_schedules_bp
from routes.portfolios import bp as portfolios_bp
from routes.households import bp as households_bp
from routes.clients import bp as clients_bp
from routes.ips import bp as ips_bp
from routes.accounts import bp as accounts_bp
from routes.fee_runs import bp as fee_runs_bp
from routes.financial_plans import bp as financial_plans_bp
from routes.goals import bp as goals_bp
from routes.rebalance import bp as rebalance_bp
from routes.reviews import bp as reviews_bp
from routes.compliance import bp as compliance_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp, fee_schedules_bp, portfolios_bp, households_bp, clients_bp,
        ips_bp, accounts_bp, fee_runs_bp, financial_plans_bp, goals_bp,
        rebalance_bp, reviews_bp, compliance_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        # Malformed JSON etc. -> treat as a field-level bad request.
        if e.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request", 400)
        return error_response("ERR_INVALID_REQUEST", str(e), e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
