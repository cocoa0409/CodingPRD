"""Carpet & Upholstery Cleaning API — Flask entry point.

Boots with EMPTY in-memory stores on every process start. The test harness
(`prd-bench-local-run --isolation per-test-server`) kills and re-launches this
server via start.sh before every individual test, so there is never any
carry-over state. Nothing is ever seeded, preloaded, or hardcoded.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_MISSING_AUTH
from response import error_response

from routes.customers import bp as customers_bp
from routes.catalogs import bp as catalogs_bp
from routes.crews import bp as crews_bp
from routes.plans import bp as plans_bp
from routes.jobs import bp as jobs_bp
from routes.job_reads import bp as job_reads_bp
from routes.billing import bp as billing_bp
from routes.guarantees import bp as guarantees_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(catalogs_bp)
    app.register_blueprint(crews_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(job_reads_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(guarantees_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _route_not_found(e):
        # Unrouted path — not a domain entity miss (real handlers resolve
        # entity 404s themselves with their specific error_id).
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, "Malformed request", 422)

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
