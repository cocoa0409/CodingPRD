"""Fundraiser Product Sale Logistics API — Flask entry point.

Boots cleanly from a fresh process: in-memory stores start empty, the logical
clock starts at 2026-08-01T00:00:00Z, and no entity data is seeded.
"""

import os
import traceback

from flask import Flask

import errors
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_clock
    import routes_campaigns
    import routes_groups
    import routes_products
    import routes_prizes
    import routes_sellers
    import routes_orders
    import routes_payments
    import routes_supplier_orders
    import routes_distribution
    import routes_claims
    import routes_returns
    import routes_prize_awards

    for module in (
        routes_clock, routes_campaigns, routes_groups, routes_products,
        routes_prizes, routes_sellers, routes_orders, routes_payments,
        routes_supplier_orders, routes_distribution, routes_claims,
        routes_returns, routes_prize_awards,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if app.debug:
            traceback.print_exc()
        return error_response("ERR_INTERNAL", 500, f"Internal error: {exc}")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
