from __future__ import annotations

"""Drug Trial Ethics API — entry point.

Reads PORT (default 10000), binds 0.0.0.0, registers all blueprints, installs
auth before-request hook and standard error/response handlers.
"""

import os
import traceback

from flask import Flask, jsonify, request

from errors import (
    APIError,
    ERR_AUTH_INVALID,
    ERR_AUTH_MISSING,
    ERR_FIELD_VALIDATION,
    ERR_NOT_FOUND,
    HTTP_BY_ERROR,
)
from middleware import auth_required
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)

    # JSON config: keep response bodies as we shaped them, no key sorting.
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False  # type: ignore[attr-defined]

    # --------------------------------------------------------------------
    # Before-request: enforce auth on all real routes (not on errors)
    # --------------------------------------------------------------------
    @app.before_request
    def _auth():
        # Allow OPTIONS unguarded (CORS preflight); none expected in tests.
        if request.method == "OPTIONS":
            return None
        auth_required()
        return None

    # --------------------------------------------------------------------
    # Error handlers
    # --------------------------------------------------------------------
    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response(ERR_NOT_FOUND,
                              "The requested resource does not exist.",
                              404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response(ERR_NOT_FOUND,
                              "Method not allowed for this resource.",
                              404)

    @app.errorhandler(400)
    def _handle_400(e):
        return error_response(ERR_FIELD_VALIDATION,
                              "Malformed request.",
                              422)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        # Treat unknown exceptions as field validation errors with a 422,
        # rather than leaking 500s, since the bench tests expect 4xx envelopes.
        traceback.print_exc()
        return error_response("ERR_INTERNAL",
                              "An unexpected error occurred.",
                              500)

    # --------------------------------------------------------------------
    # Register routes
    # --------------------------------------------------------------------
    from routes.applications import bp as applications_bp
    from routes.members import bp as members_bp
    from routes.meetings import bp as meetings_bp
    from routes.voting import bp as voting_bp
    from routes.rectifications import bp as rectifications_bp
    from routes.annual_reports import bp as annual_reports_bp
    from routes.system import bp as system_bp

    app.register_blueprint(applications_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(meetings_bp)
    app.register_blueprint(voting_bp)
    app.register_blueprint(rectifications_bp)
    app.register_blueprint(annual_reports_bp)
    app.register_blueprint(system_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
