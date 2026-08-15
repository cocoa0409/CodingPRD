"""Crop Hail & Livestock Mortality Insurance API — Flask entry point.

In-memory only; the store starts empty on every boot and nothing is seeded.
Each carrier's logical clock starts at exactly 2026-08-01T00:00:00Z (PRD 2.5)
and moves only via POST /carriers/{carrierId}/_clock/set_current_utc.
"""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.carriers import bp as carriers_bp
from routes.growers import bp as growers_bp
from routes.adjusters import bp as adjusters_bp
from routes.rate_tables import bp as rate_tables_bp
from routes.federal import bp as federal_bp
from routes.policies import bp as policies_bp
from routes.coverage_units import bp as coverage_units_bp
from routes.reports import bp as reports_bp
from routes.claims import bp as claims_bp
from routes.inspections import bp as inspections_bp
from routes.vet_reports import bp as vet_reports_bp
from routes.determinations import bp as determinations_bp
from routes.payments import bp as payments_bp
from routes.dual_links import bp as dual_links_bp
from routes.renewals import bp as renewals_bp
from routes.premium_payments import bp as premium_payments_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in (
        carriers_bp,
        growers_bp,
        adjusters_bp,
        rate_tables_bp,
        federal_bp,
        policies_bp,
        coverage_units_bp,
        reports_bp,
        claims_bp,
        inspections_bp,
        vet_reports_bp,
        determinations_bp,
        payments_bp,
        dual_links_bp,
        renewals_bp,
        premium_payments_bp,
    ):
        app.register_blueprint(blueprint)

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
