"""Marina Slip Rental API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test via start.sh, so there is no carry-over state. No entity
seeding happens at startup — every row tests need is created through the
declared API surface.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.clock import bp as clock_bp
from routes.marinas import bp as marinas_bp
from routes.slips import bp as slips_bp
from routes.tenants import bp as tenants_bp
from routes.vessels import bp as vessels_bp
from routes.leases import bp as leases_bp
from routes.pump_out import bp as pump_out_bp
from routes.tow_assist import bp as tow_assist_bp
from routes.transfer_waitlist import bp as transfer_waitlist_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(clock_bp)
    app.register_blueprint(marinas_bp)
    app.register_blueprint(slips_bp)
    app.register_blueprint(tenants_bp)
    app.register_blueprint(vessels_bp)
    app.register_blueprint(leases_bp)
    app.register_blueprint(pump_out_bp)
    app.register_blueprint(tow_assist_bp)
    app.register_blueprint(transfer_waitlist_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(_):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(
            ERR_INVALID_REQUEST,
            str(getattr(e, "description", e)) or "bad request",
            400,
        )

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response(
                ERR_INVALID_REQUEST,
                e.description or str(e),
                e.code or 500,
            )
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
