"""Personal Injury Case Management API — Flask entry point.

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

from routes.clock import bp as clock_bp
from routes.clients import bp as clients_bp
from routes.cases import bp as cases_bp
from routes.medical_providers import bp as medical_providers_bp
from routes.medical_records import bp as medical_records_bp
from routes.damages_items import bp as damages_items_bp
from routes.medical_liens import bp as medical_liens_bp
from routes.demand_letters import bp as demand_letters_bp
from routes.settlement_offers import bp as settlement_offers_bp
from routes.court_events import bp as court_events_bp
from routes.disbursements import bp as disbursements_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(clock_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(medical_providers_bp)
    app.register_blueprint(medical_records_bp)
    app.register_blueprint(damages_items_bp)
    app.register_blueprint(medical_liens_bp)
    app.register_blueprint(demand_letters_bp)
    app.register_blueprint(settlement_offers_bp)
    app.register_blueprint(court_events_bp)
    app.register_blueprint(disbursements_bp)

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
        msg = e.description if isinstance(e, HTTPException) else str(e)
        return error_response(ERR_INVALID_REQUEST, msg or "Bad request", 400)

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
