"""Telecom & SaaS Expense Management (TEM) API — Flask entry point.

In-memory storage only; the store is wiped on every process boot and no
entity data is seeded at startup. Boots cleanly under
`prd-bench-local-run --isolation per-test-server`.
"""
import os

from flask import Flask, jsonify

import core
from core import ApiError, error_body, _meta
from routes_inventory import bp as inventory_bp
from routes_invoice import bp as invoice_bp
from routes_costcenter import bp as costcenter_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(inventory_bp)
    app.register_blueprint(invoice_bp)
    app.register_blueprint(costcenter_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err)

    @app.errorhandler(404)
    def handle_not_found(_e):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND",
                     "message": "Resource or route not found."},
        }
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(_e):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_METHOD_NOT_ALLOWED",
                     "message": "Method not allowed."},
        }
        return jsonify(body), 405

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_body(err)
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
