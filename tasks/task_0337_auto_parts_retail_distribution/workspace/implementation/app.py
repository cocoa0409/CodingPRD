"""Auto Parts Retail & Distribution API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test, so there is no carry-over state and nothing is ever seeded.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST
from response import error_response

from routes.parts import bp as parts_bp
from routes.catalog import bp as catalog_bp
from routes.accounts import bp as accounts_bp
from routes.sales_orders import bp as sales_orders_bp
from routes.order_lines import bp as order_lines_bp
from routes.core_returns import bp as core_returns_bp
from routes.warranty_claims import bp as warranty_claims_bp
from routes.reorder_requests import bp as reorder_requests_bp
from routes.delivery import bp as delivery_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(parts_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(sales_orders_bp)
    app.register_blueprint(order_lines_bp)
    app.register_blueprint(core_returns_bp)
    app.register_blueprint(warranty_claims_bp)
    app.register_blueprint(reorder_requests_bp)
    app.register_blueprint(delivery_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        # Unknown route — return an error envelope (no specific resource id).
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, "Malformed request", 422)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        if isinstance(e, HTTPException):
            code = e.code or 500
            if code == 404:
                return error_response("ERR_NOT_FOUND", "Route not found", 404)
            if code == 405:
                return error_response("ERR_NOT_FOUND", "Method not allowed", 404)
            if code == 400:
                return error_response(ERR_INVALID_REQUEST, "Malformed request", 422)
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), code)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
