"""Cyber Insurance Underwriting & Incident Response API.

A single-process Flask application whose entire state lives in memory (see db.py).
Nothing is seeded, preloaded, or persisted: a fresh process starts with every table
empty and the logical clock reading 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from errors import ApiError
from response import error_response
from routes.catalog import bp as catalog_bp
from routes.claims import bp as claims_bp
from routes.policies import bp as policies_bp
from routes.proofs import bp as proofs_bp
from routes.renewal import bp as renewal_bp
from routes.underwriting import bp as underwriting_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(underwriting_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(proofs_bp)
    app.register_blueprint(renewal_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        return error_response(errors.ERR_INVALID_REQUEST,
                              exc.description or "request could not be served", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", str(exc) or "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=False, use_reloader=False)
