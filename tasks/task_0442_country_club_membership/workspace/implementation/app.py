"""Country Club Membership API — entry point, error handlers, route registration.

In-memory storage only; the store starts EMPTY on every process boot. No seeding.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clubs import bp as clubs_bp
from routes.categories import bp as categories_bp
from routes.resources import bp as resources_bp
from routes.memberships import bp as memberships_bp
from routes.reservations import bp as reservations_bp
from routes.chits import bp as chits_bp
from routes.guest_passes import bp as guest_passes_bp
from routes.assessments import bp as assessments_bp
from routes.waitlist import bp as waitlist_bp
from routes.statements import bp as statements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clubs_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(chits_bp)
    app.register_blueprint(guest_passes_bp)
    app.register_blueprint(assessments_bp)
    app.register_blueprint(waitlist_bp)
    app.register_blueprint(statements_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route -> ERR_NOT_FOUND in the standard envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {err}", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
