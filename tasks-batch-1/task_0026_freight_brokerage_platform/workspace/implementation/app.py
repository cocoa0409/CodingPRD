"""Freight Brokerage Platform API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test, so there is no carry-over state.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_FOUND,
)
from response import error_response

from routes.shippers import bp as shippers_bp
from routes.carriers import bp as carriers_bp
from routes.contract_rates import bp as contract_rates_bp
from routes.quote_requests import bp as quote_requests_bp
from routes.loads import bp as loads_bp
from routes.invoices import bp as invoices_bp
from routes.factoring_requests import bp as factoring_requests_bp
from routes.dispute_claims import bp as dispute_claims_bp
from routes.smartway_audits import bp as smartway_audits_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(shippers_bp)
    app.register_blueprint(carriers_bp)
    app.register_blueprint(contract_rates_bp)
    app.register_blueprint(quote_requests_bp)
    app.register_blueprint(loads_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(factoring_requests_bp)
    app.register_blueprint(dispute_claims_bp)
    app.register_blueprint(smartway_audits_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(_):
        return error_response(ERR_RESOURCE_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_):
        return error_response(ERR_RESOURCE_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, str(e), 400)

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
    # Serve via waitress (production WSGI) instead of Flask's dev server.
    # Werkzeug's threaded dev server can drop connections under concurrent load
    # (8 parallel test sweeps × per-test-server restart amplifies this).
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
