"""Entry point: Flask app, error handlers, blueprint registration.

In-memory only. The store starts empty on every boot (no seeding).
"""
import os

from flask import Flask

import errors
from response import error_response

from routes.config import bp as config_bp
from routes.guardians import bp as guardians_bp
from routes.members import bp as members_bp
from routes.memberships import bp as memberships_bp
from routes.sessions import bp as sessions_bp
from routes.enrollments import bp as enrollments_bp
from routes.badge_awards import bp as badge_awards_bp
from routes.showcases import bp as showcases_bp
from routes.showcase_entries import bp as showcase_entries_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(guardians_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(badge_awards_bp)
    app.register_blueprint(showcases_bp)
    app.register_blueprint(showcase_entries_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.ERR_RESOURCE_NOT_FOUND, 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errors.ERR_RESOURCE_NOT_FOUND, 404, "Resource not found.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INTERNAL", 500, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
