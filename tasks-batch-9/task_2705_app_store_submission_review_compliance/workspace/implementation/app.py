"""App Store Submission Compliance API — Flask entrypoint.

State lives in process memory only (see common.DB); a fresh process starts with
every collection empty and the logical clock at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

from common import ApiError, error_response
import routes_accounts
import routes_apps
import routes_commerce
import routes_guidelines
import routes_reviews
import routes_rollouts
import routes_submissions


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_accounts.bp)
    app.register_blueprint(routes_apps.bp)
    app.register_blueprint(routes_guidelines.bp)
    app.register_blueprint(routes_submissions.bp)
    app.register_blueprint(routes_reviews.bp)
    app.register_blueprint(routes_rollouts.bp)
    app.register_blueprint(routes_commerce.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_VALIDATION", "unknown route")

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_VALIDATION", "method not allowed for this route")

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return error_response("ERR_VALIDATION", "malformed request")

    return app


application = create_app()

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
                    threaded=False)
