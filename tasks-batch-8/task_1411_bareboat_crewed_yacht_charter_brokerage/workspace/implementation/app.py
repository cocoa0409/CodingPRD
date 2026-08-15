"""Bareboat & Crewed Yacht Charter Brokerage API — entry point.

Flask app: auth before_request, blueprint registration, envelope-shaped error
handlers. Binds 0.0.0.0:$PORT (default 10000). Store is in-memory and starts
empty on every boot.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from httpkit import ApiError, api_err, authenticate, respond_error
import routes_agreements
import routes_core
import routes_expenses
import routes_insurance
import routes_itinerary
import routes_requests
import routes_yachts


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.before_request(authenticate)

    for bp in (
        routes_core.bp,
        routes_yachts.bp,
        routes_requests.bp,
        routes_agreements.bp,
        routes_expenses.bp,
        routes_insurance.bp,
        routes_itinerary.bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return respond_error(err)

    @app.errorhandler(HTTPException)
    def _handle_http_error(err):
        if err.code == 405:
            return respond_error(
                api_err("ERR_NOT_FOUND", "Method not allowed on this path")
            )
        return respond_error(api_err("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return respond_error(ApiError("ERR_INVALID_REQUEST", str(err), 500))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
