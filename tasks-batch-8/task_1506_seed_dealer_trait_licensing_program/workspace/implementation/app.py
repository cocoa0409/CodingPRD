"""Seed Dealer & Trait Licensing Program API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_body

from routes.clock import bp as clock_bp
from routes.programs import bp as programs_bp
from routes.catalog import bp as catalog_bp
from routes.growers import bp as growers_bp
from routes.agreements import bp as agreements_bp
from routes.recommendations import bp as recommendations_bp
from routes.orders import bp as orders_bp
from routes.inventory import bp as inventory_bp
from routes.deliveries import bp as deliveries_bp
from routes.returns import bp as returns_bp
from routes.claims import bp as claims_bp
from routes.plots import bp as plots_bp
from routes.commissions import bp as commissions_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        clock_bp,
        programs_bp,
        catalog_bp,
        growers_bp,
        agreements_bp,
        recommendations_bp,
        orders_bp,
        inventory_bp,
        deliveries_bp,
        returns_bp,
        claims_bp,
        plots_bp,
        commissions_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_body(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_body(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_body(ERR_INVALID_REQUEST, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", f"internal error: {exc}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
