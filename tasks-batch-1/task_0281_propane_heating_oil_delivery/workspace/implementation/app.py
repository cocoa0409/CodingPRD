"""Propane / Heating Oil Delivery API — Flask entry point.

In-memory only. No seeding at startup. start.sh re-launches this process before
every test, wiping all state.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import errors
from response import error_response

from routes.accounts import bp as accounts_bp
from routes.price_plans import bp as price_plans_bp
from routes.tanks import bp as tanks_bp
from routes.readings import bp as readings_bp
from routes.market_prices import bp as market_prices_bp
from routes.leases import bp as leases_bp
from routes.inspections import bp as inspections_bp
from routes.trucks import bp as trucks_bp
from routes.orders import bp as orders_bp
from routes.budget_plans import bp as budget_plans_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(accounts_bp)
    app.register_blueprint(price_plans_bp)
    app.register_blueprint(tanks_bp)
    app.register_blueprint(readings_bp)
    app.register_blueprint(market_prices_bp)
    app.register_blueprint(leases_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(trucks_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(budget_plans_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> treat as not found in the standard envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # 400 from malformed JSON, etc.
        if exc.code == 400:
            return error_response(errors.ERR_INVALID_REQUEST, "Bad request", 400)
        if exc.code in (404, 405):
            return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)
        return error_response("ERR_INTERNAL", str(exc), exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
