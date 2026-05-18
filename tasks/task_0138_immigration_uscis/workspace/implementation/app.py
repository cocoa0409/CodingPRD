"""Flask application entry point for the USCIS Immigration API."""
from __future__ import annotations

import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

from config import HOST, PORT
from db import DataStore, store
import db as db_module
from errors import ApiError
from response import error as error_response, success

# Route blueprints.
from routes.biometrics import bp as biometrics_bp
from routes.case_type_config import bp as case_type_config_bp
from routes.cases import bp as cases_bp
from routes.clock import bp as clock_bp
from routes.interviews import bp as interviews_bp
from routes.petitioners import bp as petitioners_bp
from routes.rfe import bp as rfe_bp
from routes.visa_bulletin import bp as visa_bulletin_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(petitioners_bp)
    app.register_blueprint(case_type_config_bp)
    app.register_blueprint(visa_bulletin_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(biometrics_bp)
    app.register_blueprint(rfe_bp)
    app.register_blueprint(interviews_bp)
    app.register_blueprint(clock_bp)

    @app.post("/__test__/reset")
    def _reset_test_state():
        """Test-only state reset. Wipes the in-memory store back to a fresh
        DataStore so tests do not contaminate each other through shared
        VisaBulletin / Case / Clock state.
        """
        new_store = DataStore()
        # Atomically replace internal dicts so any imported `from db import store`
        # references continue to see the same singleton with empty contents.
        store.petitioners.clear()
        store.beneficiaries.clear()
        store.case_type_configs.clear()
        store.case_type_configs_by_type.clear()
        store.cases.clear()
        store.biometrics.clear()
        store.rfes.clear()
        store.interviews.clear()
        store.visa_bulletins.clear()
        store.case_events.clear()
        store.receipt_sequences.clear()
        store.receipt_numbers.clear()
        store.chart_in_effect = "FINAL_ACTION"
        # Reset the logical clock to wall-now.
        from datetime import datetime, timezone
        store.clock._logical = datetime.now(timezone.utc)
        store.clock._tick = 0
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
        return error_response("ERR_VALIDATION", getattr(exc, "description", None) or "Bad Request", 422)

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
