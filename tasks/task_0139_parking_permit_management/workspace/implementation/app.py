"""Parking & Permit Management API — Flask entry point.

Boots with empty in-memory stores (db.py). The test harness restarts this
process before every test (`--isolation per-test-server`), so there is no
carry-over state and NOTHING is seeded.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.garages import bp as garages_bp
from routes.zones import bp as zones_bp
from routes.spaces import bp as spaces_bp
from routes.rate_plans import bp as rate_plans_bp
from routes.event_pricing import bp as event_pricing_bp
from routes.motorists import bp as motorists_bp
from routes.permits import bp as permits_bp
from routes.waitlist_entries import bp as waitlist_entries_bp
from routes.merchants import bp as merchants_bp
from routes.sessions import bp as sessions_bp
from routes.plate_reads import bp as plate_reads_bp
from routes.citations import bp as citations_bp
from routes.appeals import bp as appeals_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        garages_bp,
        zones_bp,
        spaces_bp,
        rate_plans_bp,
        event_pricing_bp,
        motorists_bp,
        permits_bp,
        waitlist_entries_bp,
        merchants_bp,
        sessions_bp,
        plate_reads_bp,
        citations_bp,
        appeals_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

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
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), e.code or 500)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
