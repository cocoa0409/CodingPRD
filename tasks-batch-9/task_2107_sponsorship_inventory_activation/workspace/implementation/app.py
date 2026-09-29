"""Sponsorship Inventory & Activation API — entry point.

The store is in-memory and starts completely empty on every boot; nothing is
seeded, preloaded or hardcoded. All state is created by clients through the
declared endpoints."""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, DEFAULT_MESSAGE
from response import error as error_response

from routes.properties import bp as properties_bp
from routes.rate_cards import bp as rate_cards_bp
from routes.inventory_assets import bp as inventory_assets_bp
from routes.sponsors import bp as sponsors_bp
from routes.contracts import bp as contracts_bp
from routes.entitlements import bp as entitlements_bp
from routes.bookings import bp as bookings_bp
from routes.proofs import bp as proofs_bp
from routes.staff import bp as staff_bp


class SerializedRequests(object):
    """Every request is applied atomically. The conserved quantities this API
    protects (reserved_units_total, scheduled_minutes, committed value) must
    not interleave, and the version guards are the declared serialization
    point rather than in-process locking."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self.lock:
            return list(self.wsgi_app(environ, start_response))


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (properties_bp, rate_cards_bp, inventory_assets_bp, sponsors_bp,
                      contracts_bp, entitlements_bp, bookings_bp, proofs_bp, staff_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            error_id = "ERR_NOT_FOUND"
        elif exc.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        else:
            error_id = "ERR_VALIDATION_FAILED" if exc.code and 400 <= exc.code < 500 else "ERR_INTERNAL"
        return error_response(error_id, exc.code or 500,
                              DEFAULT_MESSAGE.get(error_id, exc.description or error_id))

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", 500, str(exc) or "Internal server error.")

    app.wsgi_app = SerializedRequests(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
