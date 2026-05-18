"""Flask application entry point for the Personal Injury Case API."""
from __future__ import annotations

import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

from config import HOST, PORT
from db import DataStore, store
from errors import ApiError
from response import error as error_response

# Route blueprints.
from routes.admin import bp as admin_bp
from routes.cases import bp as cases_bp
from routes.clients import bp as clients_bp
from routes.contingency_fee import bp as contingency_fee_bp
from routes.court_events import bp as court_events_bp
from routes.damages import bp as damages_bp
from routes.demand_letters import bp as demand_letters_bp
from routes.liens import bp as liens_bp
from routes.medical_records import bp as medical_records_bp
from routes.settlement_offers import bp as settlement_offers_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clients_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(contingency_fee_bp)
    app.register_blueprint(medical_records_bp)
    app.register_blueprint(damages_bp)
    app.register_blueprint(liens_bp)
    app.register_blueprint(demand_letters_bp)
    app.register_blueprint(settlement_offers_bp)
    app.register_blueprint(court_events_bp)
    app.register_blueprint(admin_bp)

    @app.post("/__test__/reset")
    def _reset_test_state():
        """Test-only state reset. Wipes the in-memory store back to a fresh
        DataStore so tests do not contaminate each other.
        """
        new = DataStore()
        store.clients.clear()
        store.cases.clear()
        store.medical_requests.clear()
        store.damages.clear()
        store.damages_by_case.clear()
        store.liens.clear()
        store.demand_letters.clear()
        store.settlement_offers.clear()
        store.fee_agreements.clear()
        store.fee_agreement_by_case.clear()
        store.court_events.clear()
        store.disbursements.clear()
        store.disbursement_by_case.clear()
        store.clock._logical = new.clock._logical
        store.clock._tick = 0
        from response import success
        return success({"reset": True}, 200)

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Not Found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_VALIDATION", "Method Not Allowed", 422)

    @app.errorhandler(400)
    def handle_400(exc):
        msg = getattr(exc, "description", None) or "Bad Request"
        return error_response("ERR_VALIDATION", msg, 422)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        return error_response("ERR_VALIDATION", exc.description or "HTTP error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_VALIDATION", str(exc) or "Server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=HOST, port=PORT, threaded=True)
