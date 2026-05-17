"""Flask application entry point."""
from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from config import HOST, PORT
from errors import ApiError
from response import error as error_response

# Route blueprints.
from routes.borrowers import bp as borrowers_bp
from routes.clock import bp as clock_bp
from routes.disbursements import bp as disbursements_bp
from routes.escrow_analyses import bp as escrow_analyses_bp
from routes.forbearance import bp as forbearance_bp
from routes.foreclosure import bp as foreclosure_bp
from routes.loans import bp as loans_bp
from routes.mediation import bp as mediation_bp
from routes.payments import bp as payments_bp
from routes.pmi import bp as pmi_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(borrowers_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(escrow_analyses_bp)
    app.register_blueprint(disbursements_bp)
    app.register_blueprint(forbearance_bp)
    app.register_blueprint(pmi_bp)
    app.register_blueprint(foreclosure_bp)
    app.register_blueprint(mediation_bp)
    app.register_blueprint(clock_bp)

    @app.get("/__test__/now")
    def test_now():
        """Test-only endpoint: return the server's logical clock as an
        ISO 8601 UTC timestamp. Lets fixtures align received_date and
        scheduled_date with the server's advancing clock so payment
        waterfalls and sweep maturations see the entities the test
        intended. Not part of the PRD's public API surface.
        """
        from db import store
        from utils import iso_now
        return jsonify({"now": iso_now(store.now())}), 200

    @app.post("/__test__/reset")
    def test_reset():
        """Test-only endpoint: wipe in-memory state between tests so the
        logical clock and all entities are reset to a clean baseline.
        Required because the implementation runs as a single long-lived
        process across the test suite; without it the clock offset and
        entities from prior tests bleed into subsequent tests.
        Not part of the PRD's public API surface.
        """
        from db import store, DataStore
        with store.lock:
            new_store = DataStore()
            store.clock = new_store.clock
            store.borrowers.clear()
            store.loans.clear()
            store.payments.clear()
            store.escrow_analyses.clear()
            store.disbursements.clear()
            store.forbearance_plans.clear()
            store.pmi_requests.clear()
            store.foreclosure_cases.clear()
            store.mediation_cases.clear()
            store.last_offer_extender.clear()
        return jsonify({"ok": True}), 200

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Not Found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_INVALID_STATE", "Method Not Allowed", 409)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        return error_response("ERR_INVALID_STATE", exc.description or "HTTP error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_INVALID_STATE", str(exc) or "Server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=HOST, port=PORT, threaded=True)
