"""Corporate Travel Management (TMC) API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
Run with `python3 app.py`; binds 0.0.0.0:$PORT (default 10000).
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from envelope import error_response

from routes.clock import bp as clock_bp
from routes.policies import bp as policies_bp
from routes.travelers import bp as travelers_bp
from routes.vendors import bp as vendors_bp
from routes.rates import bp as rates_bp
from routes.trips import bp as trips_bp
from routes.bookings import bp as bookings_bp
from routes.groups import bp as groups_bp
from routes.credits import bp as credits_bp
from routes.invoices import bp as invoices_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (clock_bp, policies_bp, travelers_bp, vendors_bp, rates_bp,
               trips_bp, bookings_bp, groups_bp, credits_bp, invoices_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if err.code == 404:
            return error_response(ERR_NOT_FOUND, "Resource not found", 404)
        if err.code in (400, 405):
            return error_response(ERR_INVALID_REQUEST, err.description or "Bad request", 400)
        return error_response("ERR_INTERNAL", err.description or "Error", err.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
