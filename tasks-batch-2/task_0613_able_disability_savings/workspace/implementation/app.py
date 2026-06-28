"""ABLE Disability Savings API — Flask entry point.

In-memory storage only; state is wiped on every process boot. No seeding.
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error_response
from middleware import get_identity

from routes.config import bp as config_bp
from routes.beneficiaries import bp as beneficiaries_bp
from routes.accounts import bp as accounts_bp
from routes.representatives import bp as representatives_bp
from routes.contributions import bp as contributions_bp
from routes.distributions import bp as distributions_bp
from routes.medicaid import bp as medicaid_bp
from routes.testdriving import bp as testdriving_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(beneficiaries_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(representatives_bp)
    app.register_blueprint(contributions_bp)
    app.register_blueprint(distributions_bp)
    app.register_blueprint(medicaid_bp)
    app.register_blueprint(testdriving_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route. Still authenticate first so a bad role gets 401.
        try:
            get_identity()
        except ApiError as ae:
            return error_response(ae.error_id, ae.message, ae.http_status)
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        try:
            get_identity()
        except ApiError as ae:
            return error_response(ae.error_id, ae.message, ae.http_status)
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
