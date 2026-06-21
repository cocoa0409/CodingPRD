"""Entry point: registers blueprints + error handlers (Corporate LMS API)."""

import os

from flask import Flask

import errors
from response import error_response

from routes.employees import bp as employees_bp
from routes.courses import bp as courses_bp
from routes.learning_paths import bp as learning_paths_bp
from routes.assignment_rules import bp as assignment_rules_bp
from routes.enrollments import bp as enrollments_bp
from routes.tracking_sessions import bp as tracking_sessions_bp
from routes.path_enrollments import bp as path_enrollments_bp
from routes.certificates import bp as certificates_bp
from routes.escalations import bp as escalations_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(employees_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(learning_paths_bp)
    app.register_blueprint(assignment_rules_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(tracking_sessions_bp)
    app.register_blueprint(path_enrollments_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(escalations_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(errors.ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INTERNAL", "Internal server error: %s" % e, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
