"""Flask app entry point — Edu Live Stream API."""
import os

from flask import Flask, jsonify, request

from errors import APIError
from response import error_response, success
from routes.admin import admin_bp
from routes.assignments import assignments_bp
from routes.chapters import chapters_bp
from routes.class_groups import class_groups_bp
from routes.courses import courses_bp
from routes.enrollments import enrollments_bp
from routes.instructors import instructors_bp
from routes.leave_requests import leave_requests_bp
from routes.live_classes import live_classes_bp
from routes.refunds import refunds_bp
from routes.watch_sessions import watch_sessions_bp


def create_app():
    app = Flask(__name__)

    # Register blueprints
    app.register_blueprint(courses_bp)
    app.register_blueprint(chapters_bp)
    app.register_blueprint(instructors_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(class_groups_bp)
    app.register_blueprint(live_classes_bp)
    app.register_blueprint(leave_requests_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(watch_sessions_bp)
    app.register_blueprint(refunds_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Default Flask 404 — translate to a generic not-found in our envelope
        return error_response(
            "ERR_COURSE_NOT_FOUND",
            "Route not found",
            404,
        )

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(
            "ERR_FORBIDDEN_ROLE",
            "Method not allowed",
            405,
        )

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(
            "ERR_INVALID_PRICING",
            "Bad request",
            400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface unexpected exceptions as a generic 500 in the envelope
        return error_response(
            "ERR_INVALID_PRICING",
            f"Internal server error: {type(e).__name__}",
            500,
        )

    @app.route("/health", methods=["GET"])
    def health():
        return success({"status": "ok"})

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
