"""Dropship & Endless Aisle Vendor Program API.

A single Flask process holding all state in memory. Nothing is seeded: every row
in the system is created through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import r_clock
import r_items
import r_lines
import r_orders
import r_returns
import r_scorecards
import r_vendors
from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(r_vendors.bp)
    app.register_blueprint(r_items.bp)
    app.register_blueprint(r_orders.bp)
    app.register_blueprint(r_lines.bp)
    app.register_blueprint(r_returns.bp)
    app.register_blueprint(r_scorecards.bp)
    app.register_blueprint(r_clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "resource not found", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "malformed request", 400)
        return error_response("ERR_INTERNAL", exc.description or "error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
