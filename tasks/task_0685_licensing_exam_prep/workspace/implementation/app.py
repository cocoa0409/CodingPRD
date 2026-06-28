"""Licensing Exam Prep API — entry point, error handlers, route registration.

In-memory only. No seeding: the store starts empty on every boot; tests build all
preconditions via the declared API surface.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.license_programs import bp as license_programs_bp
from routes.subscription_plans import bp as subscription_plans_bp
from routes.ce_bundles import bp as ce_bundles_bp
from routes.learners import bp as learners_bp
from routes.enrollments import bp as enrollments_bp
from routes.claims import bp as claims_bp
from routes.cohorts import bp as cohorts_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(license_programs_bp)
    app.register_blueprint(subscription_plans_bp)
    app.register_blueprint(ce_bundles_bp)
    app.register_blueprint(learners_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(cohorts_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        # Method not allowed on a known path — treat as forbidden role-shaped? No:
        # surface as not-found semantics are wrong. Use a generic invalid request.
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Surface unexpected server errors in the standard envelope.
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
