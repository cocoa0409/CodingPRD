"""Aquaculture Fish Farm API — Flask entry point.

Registers all route blueprints, installs the standard error envelope handler,
and binds 0.0.0.0:$PORT. Storage is in-memory only (see db.py); nothing is
seeded at startup — every entity is created by clients via the API surface."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error_response

from routes.reference import bp as reference_bp
from routes.cohorts import bp as cohorts_bp
from routes.stocking_grading import bp as stocking_grading_bp
from routes.health import bp as health_bp
from routes.harvest_processing import bp as harvest_processing_bp
from routes.sales import bp as sales_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(cohorts_bp)
    app.register_blueprint(stocking_grading_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(harvest_processing_bp)
    app.register_blueprint(sales_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Referenced resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed for this resource.", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, HTTPException):
            return error_response("ERR_INVALID_REQUEST", str(exc), exc.code or 400)
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
