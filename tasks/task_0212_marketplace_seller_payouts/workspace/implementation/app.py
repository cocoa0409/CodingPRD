"""Marketplace Seller Payouts API — Flask entry point.

In-memory storage only; the store starts EMPTY on every process boot. No
seeding, no preloaded entities — every entity is created by tests through the
declared API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response

from routes.sellers import bp as sellers_bp
from routes.payout_methods import bp as payout_methods_bp
from routes.fee_schedules import bp as fee_schedules_bp
from routes.orders import bp as orders_bp
from routes.ledger_entries import bp as ledger_entries_bp
from routes.refunds import bp as refunds_bp
from routes.chargebacks import bp as chargebacks_bp
from routes.disputes import bp as disputes_bp
from routes.payouts import bp as payouts_bp
from routes.tax_forms import bp as tax_forms_bp
from routes.balance_statements import bp as balance_statements_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        sellers_bp, payout_methods_bp, fee_schedules_bp, orders_bp,
        ledger_entries_bp, refunds_bp, chargebacks_bp, disputes_bp,
        payouts_bp, tax_forms_bp, balance_statements_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / path-not-found — surface as the catalogue's NOT_FOUND.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Re-raise framework HTTP exceptions to their own handlers above.
        if isinstance(exc, HTTPException):
            return exc
        return error_response("ERR_INVALID_REQUEST", "Unexpected error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
