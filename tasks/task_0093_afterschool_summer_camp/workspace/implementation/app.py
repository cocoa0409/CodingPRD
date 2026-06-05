"""Afterschool & Summer Camp Registration API — Flask entry point.

Boots with empty in-memory stores (db.py). The test harness restarts this
process via start.sh before every test, so there is NO carry-over state and
NOTHING is seeded at startup. Every entity is created by tests through the
declared API surface.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.guardians import bp as guardians_bp
from routes.children import bp as children_bp
from routes.programs import bp as programs_bp
from routes.offerings import bp as offerings_bp
from routes.scholarships import bp as scholarships_bp
from routes.enrollments import bp as enrollments_bp
from routes.billing import bp as billing_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(guardians_bp)
    app.register_blueprint(children_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(offerings_bp)
    app.register_blueprint(scholarships_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(billing_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(_):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, str(e), 400)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), e.code or 500)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
