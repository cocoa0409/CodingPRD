"""Standardized Test Registration Management API — entry point.

In-memory only. No seeding, preloading, or hardcoded entities at startup.
The store is created fresh on every process boot (db.store).
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response, object_response
from middleware import authenticate

from routes.centers import bp as centers_bp
from routes.sessions import bp as sessions_bp
from routes.candidates import bp as candidates_bp
from routes.registrations import bp as registrations_bp
from routes.accommodations import bp as accommodations_bp
from routes.standby import bp as standby_bp
from routes.scores import bp as scores_bp
from routes.clep import bp as clep_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(centers_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(candidates_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(accommodations_bp)
    app.register_blueprint(standby_bp)
    app.register_blueprint(scores_bp)
    app.register_blueprint(clep_bp)
    app.register_blueprint(clock_bp)

    # ----- Error handlers -----
    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route. Still authenticate first so an unauthenticated caller
        # never learns whether a route exists (PRD §2.6). If auth fails, surface
        # ERR_UNAUTHENTICATED; otherwise ERR_NOT_FOUND.
        try:
            authenticate()
        except ApiError as ae:
            return error_response(ae.error_id, ae.message, ae.http_status)
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        try:
            authenticate()
        except ApiError as ae:
            return error_response(ae.error_id, ae.message, ae.http_status)
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        # Surface unexpected errors as a generic 500 in the envelope.
        return error_response("ERR_INTERNAL", str(e), 500)

    @app.route("/health", methods=["GET"])
    def health():
        return object_response({"status": "ok"}, 200)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
