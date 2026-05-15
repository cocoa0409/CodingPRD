"""University Application Platform API — Flask entry point."""
from __future__ import annotations

import os
import traceback

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from core.auth import authenticate
from core.errors import ApiError
from core.ids import new_request_id
from core.response import error_response
from routes.applicants import bp as applicants_bp
from routes.applications import bp as applications_bp
from routes.clock_route import bp as clock_bp
from routes.essays import bp as essays_bp
from routes.financial_aid import bp as financial_aid_bp
from routes.recommendations import bp as recommendations_bp
from routes.universities import bp as universities_bp
from routes.waitlist import bp as waitlist_bp
from routes.yield_management import bp as yield_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Skip auth on these paths (none — every endpoint requires auth in this PRD).
    @app.before_request
    def _attach_request_id():
        # Mint and stash a request id so success/error responses agree on it.
        request._api_request_id = new_request_id()

    @app.before_request
    def _auth_gate():
        if request.method == "OPTIONS":
            return None
        # Auth applies to all real endpoints.
        authenticate()
        return None

    # Blueprints
    app.register_blueprint(applicants_bp)
    app.register_blueprint(universities_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(essays_bp)
    app.register_blueprint(recommendations_bp)
    app.register_blueprint(financial_aid_bp)
    app.register_blueprint(waitlist_bp)
    app.register_blueprint(yield_bp)
    app.register_blueprint(clock_bp)

    # ----- Error handling -----
    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _route_not_found(_err):
        return error_response(
            "ERR_RESOURCE_NOT_FOUND",
            "The requested route or resource does not exist.",
            404,
        )

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return error_response(
            "ERR_VALIDATION",
            "Method not allowed for this path.",
            405,
        )

    @app.errorhandler(HTTPException)
    def _http_err(err: HTTPException):
        return error_response("ERR_VALIDATION", err.description or err.name, err.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(err: Exception):
        traceback.print_exc()
        return error_response("ERR_VALIDATION", f"Unexpected server error: {err}", 500)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False)
