"""BOPIS & Curbside Pickup API — entry point.

In-memory only. No seeding. The store starts empty on every boot; start.sh
re-invocation creates a fresh process and wipes all state.
"""

import os

from flask import Flask, request

from errors import ApiError
from response import error_response
from db import db

from routes.customers import bp as customers_bp
from routes.stores import bp as stores_bp
from routes.products import bp as products_bp
from routes.store_inventory import bp as store_inventory_bp
from routes.pickup_slots import bp as pickup_slots_bp
from routes.orders import bp as orders_bp
from routes.order_lines import bp as order_lines_bp
from routes.substitutions import bp as substitutions_bp
from routes.curbside import bp as curbside_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (customers_bp, stores_bp, products_bp, store_inventory_bp,
               pickup_slots_bp, orders_bp, order_lines_bp, substitutions_bp,
               curbside_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "unexpected error: %s" % e, 400)

    # Serialize mutating requests so in-process state stays consistent under the
    # OCC/concurrency tests (single-process Flask dev server, threaded=True).
    @app.before_request
    def _acquire():
        db.lock.acquire()

    @app.teardown_request
    def _release(exc):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
