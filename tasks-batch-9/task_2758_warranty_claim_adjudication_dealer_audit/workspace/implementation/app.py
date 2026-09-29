"""Warranty Claim Adjudication & Dealer Audit API — entry point.

Storage is in-memory only and every store starts empty on every boot: no entity
is seeded, preloaded or hardcoded here. All state is created by clients through
the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.audits import bp as audits_bp
from routes.claims import bp as claims_bp
from routes.goodwill import bp as goodwill_bp
from routes.parts_returns import bp as parts_returns_bp
from routes.rates import bp as rates_bp
from routes.reference import bp as reference_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.register_blueprint(reference_bp)
    app.register_blueprint(rates_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(goodwill_bp)
    app.register_blueprint(parts_returns_bp)
    app.register_blueprint(audits_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            return response.error("ERR_VALIDATION", "No such route.", 404)
        if status == 405:
            return response.error("ERR_VALIDATION", "Method not allowed on this route.", 405)
        if status == 400:
            return response.error("ERR_VALIDATION", "The request body could not be parsed.", 422)
        return response.error("ERR_VALIDATION", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error("ERR_VALIDATION", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
