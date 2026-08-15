"""Structural Steel Fabrication API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The in-memory store starts empty on every
boot; nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError, ERR_INTERNAL, ERR_NOT_FOUND
from routes import (
    backcharges,
    billings,
    clock,
    drawings,
    fixes,
    inspections,
    jobs,
    loads,
    mill_orders,
    pieces,
    sequences,
    welders,
    welds,
)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        if isinstance(e, HTTPException):
            status = e.code or 500
            error_id = ERR_NOT_FOUND if status in (404, 405) else ERR_INTERNAL
            return error_response(error_id, status, e.description or "Error")
        return error_response(ERR_INTERNAL, 500, "Internal server error.")

    for module in (
        clock,
        jobs,
        drawings,
        mill_orders,
        sequences,
        pieces,
        welders,
        welds,
        inspections,
        loads,
        fixes,
        backcharges,
        billings,
    ):
        app.register_blueprint(module.bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
