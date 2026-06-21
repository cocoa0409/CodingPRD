"""Apparel Boutique & Fitting-Room Retail API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.boutiques import bp as boutiques_bp
from routes.customers import bp as customers_bp
from routes.styles import bp as styles_bp
from routes.markdowns import bp as markdowns_bp
from routes.fitting_rooms import bp as fitting_rooms_bp
from routes.stylists import bp as stylists_bp
from routes.sales_orders import bp as sales_orders_bp
from routes.returns import bp as returns_bp
from routes.special_orders import bp as special_orders_bp
from routes.lookbooks import bp as lookbooks_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        boutiques_bp, customers_bp, styles_bp, markdowns_bp, fitting_rooms_bp,
        stylists_bp, sales_orders_bp, returns_bp, special_orders_bp, lookbooks_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        # Map any other werkzeug HTTP error (e.g. 400 bad JSON) into the envelope.
        if e.code == 400:
            return error_response("ERR_INVALID_REQUEST", e.description or "Bad request", 400)
        return error_response("ERR_INVALID_REQUEST", e.description or "Error", e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
