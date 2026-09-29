"""Short-Term Rental Guest Screening and Damage Protection Platform.

Flask application entry point.  Storage is in-memory only and starts empty on
every boot -- no entity data is ever seeded, preloaded or hardcoded.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
import routes_accounts
import routes_blocklist
import routes_claims
import routes_guest
import routes_property


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_accounts.bp)
    app.register_blueprint(routes_property.bp)
    app.register_blueprint(routes_guest.bp)
    app.register_blueprint(routes_claims.bp)
    app.register_blueprint(routes_blocklist.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_response(exc.error_id, exc.message)), \
            exc.http_status

    @app.errorhandler(404)
    def handle_not_found(exc):
        return jsonify(error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return jsonify(error_response(
            "ERR_METHOD_NOT_ALLOWED",
            "That method is not allowed on this path")), 405

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return jsonify(error_response(
            "ERR_INVALID_REQUEST", "The request could not be understood")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        if isinstance(exc, HTTPException):
            code = exc.code or 500
            if code == 404:
                return handle_not_found(exc)
            if code == 405:
                return handle_method_not_allowed(exc)
            return jsonify(error_response(
                "ERR_INVALID_REQUEST",
                exc.description or "The request could not be understood")), \
                code
        return jsonify(error_response(
            "ERR_INTERNAL", "An unexpected internal error occurred")), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=True)
