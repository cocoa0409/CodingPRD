"""Food Delivery Marketplace API — entry point, error handlers, route wiring.

In-memory store only (db.py). The store is empty on every boot — no seeding,
preloading, or hardcoded entities.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error_response
from routes.zones import bp as zones_bp
from routes.restaurants import bp as restaurants_bp
from routes.parties import bp as parties_bp
from routes.orders import bp as orders_bp
from routes.deliveries import bp as deliveries_bp
from routes.issues import bp as issues_bp


def create_app():
    app = Flask(__name__)

    app.register_blueprint(zones_bp)
    app.register_blueprint(restaurants_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(deliveries_bp)
    app.register_blueprint(issues_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> generic not found in the standard envelope.
        return error_response("ERR_ORDER_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_INVALID_PAYLOAD, 400, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(errors.ERR_INVALID_PAYLOAD, 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        if isinstance(exc, HTTPException):
            return error_response(errors.ERR_INVALID_PAYLOAD, exc.code or 500, str(exc))
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve through waitress when available: the Werkzeug dev server can drop a
    # connection mid-handshake under the heavy concurrent boot load of the
    # parallel stability sweep (surfacing as a client-side BadStatusLine).
    # waitress is a robust multi-threaded WSGI server that avoids this.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
