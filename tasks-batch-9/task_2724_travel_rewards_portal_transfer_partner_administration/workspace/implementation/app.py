"""Travel Rewards Portal & Transfer Partner Administration API.

Flask application factory and entry point.  All state is process-local and
in-memory: every collection starts empty on every boot and nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import error_body
from errors import ApiError

import r_accounts
import r_agency
import r_agreements
import r_catalog
import r_clock
import r_fraud
import r_liability
import r_notices
import r_orders
import r_transactions
import r_transfers

API_PREFIX = "/rewards"

BLUEPRINTS = (
    r_clock.bp,
    r_accounts.bp,
    r_catalog.bp,
    r_transactions.bp,
    r_agency.bp,
    r_orders.bp,
    r_agreements.bp,
    r_transfers.bp,
    r_fraud.bp,
    r_notices.bp,
    r_liability.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 400:
            return error_body("ERR_INVALID_REQUEST", "Invalid request: malformed body."), 400
        if exc.code in (404, 405):
            return error_body("ERR_RESOURCE_NOT_FOUND", "Resource not found."), 404
        return error_body("ERR_INVALID_REQUEST", exc.description or "Invalid request."), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INVALID_REQUEST", "Invalid request: %s." % exc), 400

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=True,
        use_reloader=False,
    )
