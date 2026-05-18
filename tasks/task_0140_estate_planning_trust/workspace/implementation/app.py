"""Flask application entry point for the Estate Planning Trust API."""
from __future__ import annotations

import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

from config import HOST, PORT
from db import store
from errors import ApiError
from response import error as error_response, success

# Route blueprints.
from routes.assets import bp as assets_bp
from routes.beneficiaries import bp as beneficiaries_bp
from routes.clock import bp as clock_bp
from routes.designations import bp as designations_bp
from routes.directives import bp as directives_bp
from routes.distributions import bp as distributions_bp
from routes.estates import bp as estates_bp
from routes.fiduciaries import bp as fiduciaries_bp
from routes.filings import bp as filings_bp
from routes.guardianships import bp as guardianships_bp
from routes.hipaa import bp as hipaa_bp
from routes.poas import bp as poas_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(estates_bp)
    app.register_blueprint(assets_bp)
    app.register_blueprint(beneficiaries_bp)
    app.register_blueprint(designations_bp)
    app.register_blueprint(fiduciaries_bp)
    app.register_blueprint(guardianships_bp)
    app.register_blueprint(hipaa_bp)
    app.register_blueprint(poas_bp)
    app.register_blueprint(directives_bp)
    app.register_blueprint(filings_bp)
    app.register_blueprint(distributions_bp)

    @app.post("/__test__/reset")
    def _reset_test_state():
        """Test-only state reset. Wipes the in-memory store back to empty."""
        from datetime import datetime, timezone
        store.estates.clear()
        store.assets.clear()
        store.beneficiaries.clear()
        store.designations.clear()
        store.fiduciaries.clear()
        store.guardianships.clear()
        store.hipaa_auths.clear()
        store.poas.clear()
        store.directives.clear()
        store.filings.clear()
        store.distributions.clear()
        store.clock._logical = datetime.now(timezone.utc)
        store.clock._tick = 0
        return success({"reset": True}, 200)

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_BAD_REQUEST", "Method Not Allowed", 400)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_BAD_REQUEST",
                              getattr(exc, "description", None) or "Bad Request", 400)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        return error_response("ERR_BAD_REQUEST",
                              exc.description or "HTTP error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_BAD_REQUEST", str(exc) or "Server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=HOST, port=PORT, threaded=True)
