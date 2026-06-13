"""Business License & Permit API — Flask entry point.

Boots a fresh in-memory store on every process start (no seeding). Registers all
resource blueprints and the global error handlers that emit the standard envelope.
"""
import os

from flask import Flask, jsonify

import errors
import response
from routes.activity_categories import bp as activity_categories_bp
from routes.businesses import bp as businesses_bp
from routes.applications import bp as applications_bp
from routes.inspections import bp as inspections_bp
from routes.licenses import bp as licenses_bp
from routes.endorsements import bp as endorsements_bp
from routes.transfers import bp as transfers_bp
from routes.fee_assessments import bp as fee_assessments_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(activity_categories_bp)
    app.register_blueprint(businesses_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(licenses_bp)
    app.register_blueprint(endorsements_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(fee_assessments_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return response.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # unknown route -> ERR_NOT_FOUND envelope
        return response.error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return response.error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return response.error_response(errors.ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return response.error_response(err.error_id, err.message, err.http_status)
        # surface unexpected errors as a generic 400 invalid request envelope
        return response.error_response(errors.ERR_INVALID_REQUEST, str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
