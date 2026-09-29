"""Competitive Price Intelligence API — application entry point.

The store is in-memory only and starts EMPTY on every boot: nothing is seeded,
preloaded or hardcoded here.  Every entity is built through the API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ERROR_STATUS, ApiError
from response import error_response
from routes import (change_orders, claims, clock_routes, competitors,
                    index_reports, label_batches, markets, matches,
                    observations, policies, products, repricing_rules, stores)

API_PREFIX = "/pricing"

BLUEPRINTS = (markets.bp, competitors.bp, products.bp, stores.bp, matches.bp,
              observations.bp, index_reports.bp, repricing_rules.bp,
              change_orders.bp, policies.bp, claims.bp, label_batches.bp,
              clock_routes.bp)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed.", 405)
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "Invalid request.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error.",
                              ERROR_STATUS["ERR_INTERNAL"])

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
