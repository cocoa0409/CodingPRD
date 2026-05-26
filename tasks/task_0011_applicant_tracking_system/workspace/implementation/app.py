"""ATS Applicant Tracking API — Flask entry point."""
import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

# Route blueprints.
from routes.departments import bp as departments_bp
from routes.requisitions import bp as requisitions_bp
from routes.candidates import bp as candidates_bp
from routes.applications import bp as applications_bp
from routes.interviews import bp as interviews_bp
from routes.offers import bp as offers_bp
from routes.background_checks import bp as background_checks_bp
from routes.referral_bonuses import bp as referral_bonuses_bp
from routes.diversity_goals import bp as diversity_goals_bp
from routes.clock_route import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    # Don't strict-slash redirect — tests address resources without trailing slashes.
    app.url_map.strict_slashes = False

    # Register all blueprints.
    for bp in (
        departments_bp,
        requisitions_bp,
        candidates_bp,
        applications_bp,
        interviews_bp,
        offers_bp,
        background_checks_bp,
        referral_bonuses_bp,
        diversity_goals_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    # ApiError handler.
    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return error_response(e.error_id, e.message, e.http_status)

    # 404 -> ERR_NOT_FOUND (path not matched on any route).
    @app.errorhandler(404)
    def _404(e):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    # 405 -> ERR_INVALID_REQUEST (method not allowed surfaces as malformed).
    @app.errorhandler(405)
    def _405(e):
        return error_response(ERR_INVALID_REQUEST, "method not allowed", 400)

    # Generic HTTPException fallback.
    @app.errorhandler(HTTPException)
    def _http(e: HTTPException):
        return error_response(ERR_INVALID_REQUEST, e.description or "bad request", e.code or 400)

    # Catch-all for unexpected exceptions.
    @app.errorhandler(Exception)
    def _unhandled(e):
        # Last resort — produce envelope-shaped error.
        return error_response(ERR_INVALID_REQUEST, f"internal: {type(e).__name__}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
