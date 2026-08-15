"""REIT Compliance & Distribution Management API — Flask entry point.

In-memory store (db.py) starts empty on every boot; no seeding. Listens on
PORT (default 10000), bound to 0.0.0.0, in the foreground.
"""

import os

from flask import Flask, jsonify

import errors
from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.reits import bp as reits_bp
from routes.asset_holdings import bp as asset_holdings_bp
from routes.quarters import bp as quarters_bp
from routes.income_items import bp as income_items_bp
from routes.test_reports import bp as test_reports_bp
from routes.shareholders import bp as shareholders_bp
from routes.distribution_requirements import bp as requirements_bp
from routes.dividend_declarations import bp as dividends_bp
from routes.ep_adjustments import bp as ep_adjustments_bp
from routes.asset_sales import bp as asset_sales_bp
from routes.compliance_disclosures import bp as disclosures_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        clock_bp,
        reits_bp,
        asset_holdings_bp,
        quarters_bp,
        income_items_bp,
        test_reports_bp,
        shareholders_bp,
        requirements_bp,
        dividends_bp,
        ep_adjustments_bp,
        asset_sales_bp,
        disclosures_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Never leak a stack trace through the envelope; treat as validation-shaped 500
        return error_response(errors.ERR_VALIDATION, f"Unexpected error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
