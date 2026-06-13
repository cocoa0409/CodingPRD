"""Food Safety & Traceability API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test (per-test-server isolation), so there is no carry-over state.
No entities are ever seeded at startup.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError
from response import error_response

from routes.facilities import bp as facilities_bp
from routes.setup import bp as setup_bp
from routes.lots import bp as lots_bp
from routes.coa import bp as coa_bp
from routes.production import bp as production_bp
from routes.ccp import bp as ccp_bp
from routes.holds import bp as holds_bp
from routes.storage import bp as storage_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(facilities_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(coa_bp)
    app.register_blueprint(production_bp)
    app.register_blueprint(ccp_bp)
    app.register_blueprint(holds_bp)
    app.register_blueprint(storage_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _route_not_found(e):
        # Unknown route — not a domain not-found; surface as a generic 404.
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 405)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_INVALID_REQUEST", e.description or str(e), e.code or 500)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
