"""Farmers Market & Vendor Booth Management API — entry point.

In-memory only. No seeding. Fresh state on every boot.
"""
import os

from flask import Flask

from errors import APIError
from response import error_response

from routes.markets import bp as markets_bp
from routes.vendors import bp as vendors_bp
from routes.assignments import bp as assignments_bp
from routes.market_days import bp as market_days_bp
from routes.check_ins import bp as check_ins_bp
from routes.sales_reports import bp as sales_reports_bp
from routes.vouchers import bp as vouchers_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(markets_bp)
    app.register_blueprint(vendors_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(market_days_bp)
    app.register_blueprint(check_ins_bp)
    app.register_blueprint(sales_reports_bp)
    app.register_blueprint(vouchers_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
