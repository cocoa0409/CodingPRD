"""Master Gardener Volunteer Program & Help Desk API — Flask entry point."""

import os
from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.program_cycles import bp as cycles_bp
from routes.applications import bp as applications_bp
from routes.volunteers import bp as volunteers_bp
from routes.training import bp as training_bp
from routes.credit_entries import bp as credit_bp
from routes.shifts import bp as shifts_bp
from routes.referrals import bp as referrals_bp
from routes.projects import bp as projects_bp
from routes.rotation import bp as rotation_bp


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    for bp in (clock_bp, cycles_bp, applications_bp, volunteers_bp, training_bp,
               credit_bp, shifts_bp, referrals_bp, projects_bp, rotation_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
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
    app.run(host="0.0.0.0", port=port)
