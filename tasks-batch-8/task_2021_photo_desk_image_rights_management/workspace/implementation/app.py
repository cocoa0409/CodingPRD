"""Photo Desk & Image Rights Management API — entry point.

Flask application factory + error handlers + route registration.
"""

import os
from flask import Flask

from errors import ApiError
from response import error_response
from db import init_store


def create_app():
    app = Flask(__name__)

    # Initialize in-memory store (empty on every boot)
    init_store()

    # Register blueprints
    from routes.photographers import bp as photographers_bp
    from routes.story_requests import bp as story_requests_bp
    from routes.assignments import bp as assignments_bp
    from routes.images import bp as images_bp
    from routes.licenses import bp as licenses_bp
    from routes.releases import bp as releases_bp
    from routes.claims import bp as claims_bp
    from routes.payment_runs import bp as payment_runs_bp
    from routes.clock import bp as clock_bp

    app.register_blueprint(photographers_bp)
    app.register_blueprint(story_requests_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(images_bp)
    app.register_blueprint(licenses_bp)
    app.register_blueprint(releases_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(payment_runs_bp)
    app.register_blueprint(clock_bp)

    # Error handlers
    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response("ERR_NOT_FOUND", "Not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 405)

    @app.errorhandler(500)
    def handle_internal_error(e):
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
