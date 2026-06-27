import os

from flask import Flask, request

import errors
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.plans import bp as plans_bp
from routes.members import bp as members_bp
from routes.memberships import bp as memberships_bp
from routes.introductions import bp as introductions_bp
from routes.date_events import bp as date_events_bp
from routes.coaching import bp as coaching_bp
from routes.background_checks import bp as background_checks_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(introductions_bp)
    app.register_blueprint(date_events_bp)
    app.register_blueprint(coaching_bp)
    app.register_blueprint(background_checks_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — generic not found
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
