"""Flask application entry point for the Trust Accounting API."""
from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from config import HOST, PORT
from errors import ApiError
from response import error as error_response

# Route blueprints.
from routes.assets import bp as assets_bp
from routes.beneficiaries import bp as beneficiaries_bp
from routes.clock import bp as clock_bp
from routes.distributions import bp as distributions_bp
from routes.k1s import bp as k1s_bp
from routes.tax_years import bp as tax_years_bp
from routes.transactions import bp as transactions_bp
from routes.trustees import bp as trustees_bp
from routes.trusts import bp as trusts_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(trusts_bp)
    app.register_blueprint(trustees_bp)
    app.register_blueprint(beneficiaries_bp)
    app.register_blueprint(assets_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(distributions_bp)
    app.register_blueprint(tax_years_bp)
    app.register_blueprint(k1s_bp)
    app.register_blueprint(clock_bp)

    @app.get("/__health__")
    def health():
        return jsonify({"ok": True}), 200

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Not Found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_INVALID_STATE", "Method Not Allowed", 409)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        return error_response("ERR_BAD_REQUEST", exc.description or "HTTP error", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_BAD_REQUEST", str(exc) or "Server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=HOST, port=PORT, threaded=True)
