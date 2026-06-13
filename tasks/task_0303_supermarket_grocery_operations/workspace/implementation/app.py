"""Supermarket / Grocery Operations API — Flask entry point."""
import os

from flask import Flask, jsonify, request

from auth import authenticate
from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.receiving import bp as receiving_bp
from routes.lots import bp as lots_bp
from routes.pricing import bp as pricing_bp
from routes.loyalty import bp as loyalty_bp
from routes.sales import bp as sales_bp
from routes.audit import bp as audit_bp
from routes.clock_admin import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth_gate():
        # Auth (priority 1) runs for every API request before any handler.
        authenticate()

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        body = error_response(e.error_id, e.message)
        return jsonify(body), e.http_status

    @app.errorhandler(404)
    def _handle_404(e):
        # Unknown route — treat as a generic not-found shaped error.
        body = error_response("ERR_NOT_FOUND", "resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(e):
        body = error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed")
        return jsonify(body), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return _handle_api_error(e)
        body = error_response("ERR_INTERNAL", str(e))
        return jsonify(body), 500

    app.register_blueprint(catalog_bp)
    app.register_blueprint(receiving_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(pricing_bp)
    app.register_blueprint(loyalty_bp)
    app.register_blueprint(sales_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(clock_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
