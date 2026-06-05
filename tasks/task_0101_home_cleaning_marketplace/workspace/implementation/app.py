"""Home Cleaning Marketplace API — Flask entry point.

In-memory storage only (see db.py). No entity seeding at startup. Binds
0.0.0.0:$PORT (default 10000) and runs in the foreground via start.sh.
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error as error_response

from routes.customers import bp as customers_bp
from routes.addresses import bp as addresses_bp
from routes.cleaners import bp as cleaners_bp
from routes.pricing_plans import bp as pricing_plans_bp
from routes.preferred_pros import bp as preferred_pros_bp
from routes.booking_series import bp as booking_series_bp
from routes.bookings import bp as bookings_bp
from routes.tips import bp as tips_bp
from routes.payouts_ledger import bp as payouts_ledger_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (customers_bp, addresses_bp, cleaners_bp, pricing_plans_bp,
               preferred_pros_bp, booking_series_bp, bookings_bp, tips_bp,
               payouts_ledger_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown path/resource. Authenticate first so a missing auth header
        # surfaces as 401, matching the validation precedence.
        from auth import authenticate
        try:
            authenticate()
        except ApiError as ae:
            return error_response(ae.error_id, ae.http_status, ae.message)
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        from auth import authenticate
        try:
            authenticate()
        except ApiError as ae:
            return error_response(ae.error_id, ae.http_status, ae.message)
        return error_response("ERR_NOT_FOUND", 404, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 400, "internal error: %s" % e)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
