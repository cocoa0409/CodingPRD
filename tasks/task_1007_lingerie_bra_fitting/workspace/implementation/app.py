"""Lingerie & Bra-Fitting Boutique API — Flask entry point.

Boots with an empty in-memory store on every process start (the harness
restarts this via start.sh before each test). No entity data is seeded.
"""
import os

from flask import Flask

import api as boutique_http
from errors import ApiError

from routes.customers import bp as customers_bp
from routes.staff import bp as staff_bp
from routes.appointments import bp as appointments_bp
from routes.catalog import bp as catalog_bp
from routes.orders import bp as orders_bp
from routes.exchanges import bp as exchanges_bp
from routes.insurance import bp as insurance_bp
from routes.reminders import bp as reminders_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth():
        boutique_http.authenticate()

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return boutique_http.error_response(err)

    for bp in (customers_bp, staff_bp, appointments_bp, catalog_bp, orders_bp,
               exchanges_bp, insurance_bp, reminders_bp, clock_bp):
        app.register_blueprint(bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
