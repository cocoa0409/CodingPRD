"""Cosmetics Contract Manufacturing API — Flask entry point.

Mounts every route module, installs the standard error envelope handlers, and
serves 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask

from core import ApiError, error_response
import routes_allocations
import routes_batches
import routes_clock
import routes_components
import routes_customers
import routes_filling
import routes_formulas
import routes_orders
import routes_reviews
import routes_shortfalls
import routes_stability


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (routes_customers, routes_components, routes_formulas,
                   routes_reviews, routes_orders, routes_batches,
                   routes_shortfalls, routes_allocations, routes_stability,
                   routes_filling, routes_clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc)
        return error_response(ApiError("ERR_VALIDATION", 400, str(exc)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
