"""Flask entry point for the Standardized Test Registration API.

Binds 0.0.0.0:$PORT (default 10000).
"""

import os

from flask import Flask, request

from errors import APIError, err_invalid_request, err_missing_or_invalid_user_context_header
from middleware import parse_headers
from response import error_response
from routes.accommodation_routes import bp as accommodation_bp
from routes.candidate_routes import bp as candidate_bp
from routes.clock_routes import bp as clock_bp
from routes.registration_routes import bp as registration_bp
from routes.score_routes import bp as score_bp
from routes.test_event_routes import bp as test_event_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Disable Flask's pretty-print so responses are compact and tests don't fight whitespace.
    app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False

    # Order matters for error precedence: clock_bp first ensures /_clock and
    # /_sweep are reachable before other route matching.
    app.register_blueprint(clock_bp)
    app.register_blueprint(test_event_bp)
    app.register_blueprint(candidate_bp)
    app.register_blueprint(registration_bp)
    app.register_blueprint(accommodation_bp)
    app.register_blueprint(score_bp)


    @app.errorhandler(APIError)
    def _handle_api_error(exc: APIError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(_e):
        # Flask 404 from a missing route — return the generic invalid-request shape
        # rather than a not-found error tied to any entity (because the URL itself
        # is unknown).
        return error_response("ERR_INVALID_REQUEST", "Endpoint not found", 404)

    @app.errorhandler(405)
    def _handle_405(_e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(400)
    def _handle_400(_e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def _handle_other(exc):
        # Re-raise APIError if it ever lands here via some wrapping path.
        if isinstance(exc, APIError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", f"Internal error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
