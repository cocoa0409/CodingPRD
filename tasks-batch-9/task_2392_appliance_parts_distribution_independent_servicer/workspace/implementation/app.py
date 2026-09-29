"""Appliance Parts Distribution & Independent Servicer Network API.

Flask application factory and process entry point.  All state lives in memory
(see db.py) and the store is empty on every boot: the harness restarts this
process before every test, and no fixture data is ever seeded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.accounts import bp as accounts_bp
from routes.catalog import bp as catalog_bp
from routes.inventory import bp as inventory_bp
from routes.orders import bp as orders_bp
from routes.pricefiles import bp as pricefiles_bp
from routes.returns import bp as returns_bp
from routes.substitutes import bp as substitutes_bp
from routes.warranty import bp as warranty_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (catalog_bp, accounts_bp, inventory_bp, pricefiles_bp,
                      orders_bp, substitutes_bp, warranty_bp, returns_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_INVALID_REQUEST", "Unknown route", 404)
        if exc.code == 405:
            return response.error("ERR_INVALID_REQUEST",
                                  "Method not allowed for this route", 405)
        if exc.code in (400, 415):
            return response.error("ERR_INVALID_REQUEST",
                                  exc.description or "Malformed request", 400)
        return response.error("ERR_INVALID_REQUEST",
                              exc.description or "Request failed",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return response.error("ERR_INVALID_REQUEST",
                             "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
