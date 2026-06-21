"""SSDI Disability Application API — Flask entrypoint."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, invalid_request
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register blueprints
    from routes.claimants import bp as claimants_bp
    from routes.work_credits import bp as work_credits_bp
    from routes.applications import bp as applications_bp
    from routes.hearings import bp as hearings_bp
    from routes.awards import bp as awards_bp
    from routes.cdr import bp as cdr_bp, clock_bp

    app.register_blueprint(claimants_bp)
    app.register_blueprint(work_credits_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(hearings_bp)
    app.register_blueprint(awards_bp)
    app.register_blueprint(cdr_bp)
    app.register_blueprint(clock_bp)

    # Global error handlers
    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND, 404, "route not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND, 404, "method not allowed")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(ERR_INVALID_REQUEST, 400, "bad request")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Surface other HTTP errors in our envelope (do not leak werkzeug HTML).
        code = e.code or 500
        # Map by best guess.
        if code == 404:
            return error_response(ERR_NOT_FOUND, 404, "route not found")
        if code == 400:
            return error_response(ERR_INVALID_REQUEST, 400, e.description or "bad request")
        return error_response("ERR_INTERNAL", code, e.description or "internal error")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Last-resort: do not leak stack traces.
        return error_response("ERR_INTERNAL", 500, f"internal error: {type(e).__name__}")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Disable the reloader so the process stays single (per-test-server isolation).
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
