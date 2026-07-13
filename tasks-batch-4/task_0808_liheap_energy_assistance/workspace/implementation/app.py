"""Application entrypoint: build the Flask app, wire routes and error handlers.

State lives only in the in-memory store (store.py), so every per-test-server
reboot via start.sh starts from an empty database.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound, MethodNotAllowed

from common import ApiError, error_response

import r_pools
import r_households
import r_applications
import r_income
import r_vendors
import r_accounts
import r_pledges
import r_crisis
import r_payments
import r_billcredits
import r_referrals

ROUTE_MODULES = (
    r_pools,
    r_households,
    r_applications,
    r_income,
    r_vendors,
    r_accounts,
    r_pledges,
    r_crisis,
    r_payments,
    r_billcredits,
    r_referrals,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in ROUTE_MODULES:
        module.register(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(NotFound)
    def _handle_not_found(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found")

    @app.errorhandler(MethodNotAllowed)
    def _handle_method_not_allowed(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found")

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        # A malformed request body surfaces as 400 before any handler runs.
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "Malformed request")
        return error_response("ERR_VALIDATION", exc.description or "Request rejected")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
