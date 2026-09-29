"""Merchant Underwriting and Portfolio Risk Monitoring API.

A single-process Flask application whose entire state lives in memory
(see db.py). Nothing is seeded: every entity is created through the API.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.applications import bp as applications_bp
from routes.enforcement import bp as enforcement_bp
from routes.portfolio import bp as portfolio_bp
from routes.settlement import bp as settlement_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(applications_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(settlement_bp)
    app.register_blueprint(enforcement_bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _handle_bad_request(_exc):
        return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(404)
    def _handle_not_found(_exc):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(_exc):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this resource.", 405)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
