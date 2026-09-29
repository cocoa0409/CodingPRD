"""Grain Merchandising & Basis Trading API — entry point.

In-memory storage only. The store starts EMPTY on every boot: no seeding,
no preloading, no hardcoded entities.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes.contracts import bp as contracts_bp
from routes.delivery import bp as delivery_bp
from routes.market import bp as market_bp
from routes.reference import bp as reference_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(market_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(delivery_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_body("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_body("ERR_NOT_FOUND", "Method not allowed.", 405)
        if exc.code == 400:
            return error_body("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error_body("ERR_INTERNAL", exc.description or "Error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return error_body("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
