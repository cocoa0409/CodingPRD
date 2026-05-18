"""Flask application entry point for the MLS Listings & Buyer Matching API."""
from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from config import HOST, PORT
from errors import ApiError
from response import error as error_response

# Blueprints.
from routes.agents import bp as agents_bp
from routes.buyers import bp as buyers_bp
from routes.clock_sweep import bp as clock_sweep_bp
from routes.commission_splits import bp as commission_splits_bp
from routes.contingencies import bp as contingencies_bp
from routes.listings import bp as listings_bp
from routes.lockboxes import bp as lockboxes_bp
from routes.offers import bp as offers_bp
from routes.showings import bp as showings_bp
from routes.test_infra import bp as test_infra_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(agents_bp)
    app.register_blueprint(buyers_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(lockboxes_bp)
    app.register_blueprint(showings_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(contingencies_bp)
    app.register_blueprint(commission_splits_bp)
    app.register_blueprint(clock_sweep_bp)
    app.register_blueprint(test_infra_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Not Found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        # Method-not-allowed doesn't fit any specific scaffold code well;
        # treat as a state error.
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
