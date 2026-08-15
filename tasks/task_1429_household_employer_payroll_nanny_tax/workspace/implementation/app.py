"""Household Employer Payroll API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.employers import bp as employers_bp
from routes.state_rule_packs import bp as state_rule_packs_bp
from routes.registrations import bp as registrations_bp
from routes.workers import bp as workers_bp
from routes.agreements import bp as agreements_bp
from routes.timesheets import bp as timesheets_bp
from routes.pay_runs import bp as pay_runs_bp
from routes.paychecks import bp as paychecks_bp
from routes.leave_requests import bp as leave_requests_bp
from routes.tax import bp as tax_bp
from routes.filings import bp as filings_bp
from routes.policies import bp as policies_bp
from routes.year_end import bp as year_end_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(employers_bp)
    app.register_blueprint(state_rule_packs_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(workers_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(timesheets_bp)
    app.register_blueprint(pay_runs_bp)
    app.register_blueprint(paychecks_bp)
    app.register_blueprint(leave_requests_bp)
    app.register_blueprint(tax_bp)
    app.register_blueprint(filings_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(year_end_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
