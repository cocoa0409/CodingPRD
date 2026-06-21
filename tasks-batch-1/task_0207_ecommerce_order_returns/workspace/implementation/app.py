"""Ecommerce Order & Returns API — Flask entry point.

In-memory only: a fresh process starts with an empty store and no seeded data.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.customers import bp as customers_bp
from routes.warehouses import bp as warehouses_bp
from routes.products import bp as products_bp
from routes.orders import bp as orders_bp
from routes.shipments import bp as shipments_bp
from routes.returns import bp as returns_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(warehouses_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        if isinstance(e, HTTPException):
            # map remaining HTTP errors to the envelope
            code = e.code or 500
            return error_response("ERR_VALIDATION", str(e), code if code >= 400 else 500)
        return error_response("ERR_VALIDATION", "Internal error: %s" % e, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer a production-grade WSGI server (waitress). The Werkzeug dev server
    # accepts TCP connections into its listen backlog before its handler loop is
    # ready, which under heavy concurrent boot load (8 parallel rounds, a server
    # reboot before every test) can surface as a BadStatusLine on the very first
    # request after a restart. waitress's accept loop is bound to its worker
    # threads, eliminating that boot-race window. Fall back to Flask's dev server
    # if waitress is unavailable so the app still runs in a bare environment.
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=8, _quiet=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
