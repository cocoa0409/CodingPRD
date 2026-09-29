"""Store Cash Office & Deposit Reconciliation API — entry point.

In-memory storage only; the store is empty on every boot and every entity is
created through the declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError, ERROR_STATUS
from routes import bank
from routes import cases
from routes import cashiers
from routes import change_orders
from routes import clock_routes
from routes import deposits
from routes import journals
from routes import safes
from routes import sessions
from routes import stores

BLUEPRINTS = (
    clock_routes.bp,
    stores.bp,
    cashiers.bp,
    safes.bp,
    journals.bp,
    sessions.bp,
    deposits.bp,
    bank.bp,
    cases.bp,
    change_orders.bp,
)

HTTP_FALLBACK_ERROR = {
    400: "ERR_INVALID_REQUEST",
    401: "ERR_UNAUTHENTICATED",
    403: "ERR_UNAUTHORIZED",
}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        error_id = HTTP_FALLBACK_ERROR.get(status, "ERR_INVALID_REQUEST")
        message = exc.description or exc.name
        return response.error_response(error_id, message, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
