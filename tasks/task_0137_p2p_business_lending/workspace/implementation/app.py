"""Flask application entry point — P2P Business Lending API."""
from __future__ import annotations

import logging

from flask import Flask
from werkzeug.exceptions import HTTPException

from config import HOST, PORT
from errors import ApiError
from response import error as error_response

# Route blueprints.
from routes.borrowers import bp as borrowers_bp
from routes.compliance_officers import bp as compliance_officers_bp
from routes.disclosures import bp as disclosures_bp
from routes.investors import bp as investors_bp
from routes.listings import bp as listings_bp
from routes.loans import bp as loans_bp
from routes.payments import bp as payments_bp
from routes.platforms import bp as platforms_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(platforms_bp)
    app.register_blueprint(borrowers_bp)
    app.register_blueprint(investors_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(disclosures_bp)
    app.register_blueprint(compliance_officers_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_INVALID_STATE_TRANSITION", "Method not allowed.", 409)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", str(getattr(exc, "description", "Bad request")), 400)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        code = exc.code or 500
        eid = "ERR_INVALID_REQUEST" if 400 <= code < 500 else "ERR_INVALID_STATE_TRANSITION"
        return error_response(eid, exc.description or "HTTP error", code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_INVALID_REQUEST", str(exc) or "Server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=HOST, port=PORT, threaded=True)
