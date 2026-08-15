"""Office Furniture Dealer & Space Planning API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    from routes import (
        dealerships, clock, customers, contracts, space_plans, product_series,
        orders, order_lines, crews, install_events, staging, punch_items,
        claims, asset_tags, liquidation_lots,
    )
    for mod in (
        dealerships, clock, customers, contracts, space_plans, product_series,
        orders, order_lines, crews, install_events, staging, punch_items,
        claims, asset_tags, liquidation_lots,
    ):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", f"unexpected error: {err}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
