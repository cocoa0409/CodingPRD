"""Flask entry point for the Online Tutoring Marketplace API."""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import APIError
from response import error_response
from routes.clock_routes import clock_bp
from routes.dispute_routes import dispute_bp
from routes.parent_routes import parent_bp
from routes.payout_routes import payout_bp
from routes.session_routes import session_bp
from routes.student_routes import student_bp
from routes.tutor_routes import tutor_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    prefix = "/tutoring"
    app.register_blueprint(tutor_bp, url_prefix=prefix)
    app.register_blueprint(student_bp, url_prefix=prefix)
    app.register_blueprint(parent_bp, url_prefix=prefix)
    app.register_blueprint(session_bp, url_prefix=prefix)
    app.register_blueprint(dispute_bp, url_prefix=prefix)
    app.register_blueprint(payout_bp, url_prefix=prefix)
    app.register_blueprint(clock_bp, url_prefix=prefix)

    @app.errorhandler(APIError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_):
        return error_response("ERR_VALIDATION", "Method not allowed.", 400)

    @app.errorhandler(400)
    def handle_400(_):
        return error_response("ERR_VALIDATION", "Bad request.", 400)

    @app.errorhandler(HTTPException)
    def handle_http(err):
        # Map any unhandled werkzeug HTTPException to ERR_VALIDATION (4xx) or 500
        if 400 <= err.code < 500:
            return error_response("ERR_VALIDATION", err.description or "Bad request.", err.code)
        return error_response("ERR_VALIDATION", "Internal error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Last-ditch — surface as 500 but in the standard envelope
        return error_response("ERR_VALIDATION", f"Unexpected error: {type(err).__name__}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
