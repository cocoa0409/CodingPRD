"""Accounts Payable Automation API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
(via start.sh) before every test, so there is no carry-over state. Nothing is
ever seeded at startup — every entity is constructed via the declared endpoints.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.vendors import bp as vendors_bp
from routes.gl_accounts import bp as gl_accounts_bp
from routes.purchase_orders import bp as purchase_orders_bp
from routes.goods_receipts import bp as goods_receipts_bp
from routes.invoices import bp as invoices_bp
from routes.match_exceptions import bp as match_exceptions_bp
from routes.approval_routes import bp as approval_routes_bp
from routes.approval_steps import bp as approval_steps_bp
from routes.payment_batches import bp as payment_batches_bp
from routes.payments import bp as payments_bp
from routes.accruals import bp as accruals_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(vendors_bp)
    app.register_blueprint(gl_accounts_bp)
    app.register_blueprint(purchase_orders_bp)
    app.register_blueprint(goods_receipts_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(match_exceptions_bp)
    app.register_blueprint(approval_routes_bp)
    app.register_blueprint(approval_steps_bp)
    app.register_blueprint(payment_batches_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(accruals_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, str(e), 400)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), e.code or 500)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
