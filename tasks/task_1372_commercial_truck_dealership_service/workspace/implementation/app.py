"""Commercial Truck Dealership API — entry point.

Flask app: registers blueprints, maps ApiError to the error envelope, binds
0.0.0.0:$PORT (default 10000). Storage is in-memory only and starts empty on
every boot.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error

from routes import (ops, accounts, slots, orders, units, appraisals,
                    resources, repair_orders, lines, bookings, claims, parts)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    for module in (ops, accounts, slots, orders, units, appraisals, resources,
                   repair_orders, lines, bookings, claims, parts):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        return error(ApiError("ERR_INVALID_REQUEST", err.code or 400,
                              err.description or "HTTP error"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error(ApiError("ERR_INVALID_REQUEST", 500, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
