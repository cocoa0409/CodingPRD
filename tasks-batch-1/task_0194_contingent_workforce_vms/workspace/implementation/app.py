"""Contingent Workforce VMS API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No seeding.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.programs import bp as programs_bp
from routes.requisitions import bp as requisitions_bp
from routes.work import bp as work_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(programs_bp)
    app.register_blueprint(requisitions_bp)
    app.register_blueprint(work_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_NOT_FOUND", "Resource not found")

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed")

    @app.errorhandler(400)
    def handle_400(_exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
