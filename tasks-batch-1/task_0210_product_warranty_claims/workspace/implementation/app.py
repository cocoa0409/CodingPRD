"""Product Warranty Claims API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test (per-test-server isolation), so there is no carry-over state.
Nothing is seeded at startup; every entity is created by tests via the API.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.products import bp as products_bp
from routes.coverage_tiers import bp as coverage_tiers_bp
from routes.owners import bp as owners_bp
from routes.registrations import bp as registrations_bp
from routes.extended_warranties import bp as extended_warranties_bp
from routes.proofs import bp as proofs_bp
from routes.claims import bp as claims_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(products_bp)
    app.register_blueprint(coverage_tiers_bp)
    app.register_blueprint(owners_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(extended_warranties_bp)
    app.register_blueprint(proofs_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _route_not_found(e):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, "Bad request", 400)

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
