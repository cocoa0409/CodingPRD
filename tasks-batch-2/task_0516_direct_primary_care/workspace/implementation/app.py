"""DPC API — Flask entry point. In-memory state; boots empty every process."""
import os

from flask import Flask

import response
from errors import ApiError

from routes.practices import bp as practices_bp
from routes.providers import bp as providers_bp
from routes.employers import bp as employers_bp
from routes.members import bp as members_bp
from routes.memberships import bp as memberships_bp
from routes.visits import bp as visits_bp
from routes.care_plans import bp as care_plans_bp
from routes.referrals import bp as referrals_bp
from routes.message_threads import bp as message_threads_bp
from routes.invoices import bp as invoices_bp
from routes.payments import bp as payments_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(practices_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(employers_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(care_plans_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(message_threads_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return response.error_response(
            "ERR_NOT_FOUND", "Resource not found.", 404
        )

    @app.errorhandler(405)
    def handle_405(err):
        return response.error_response(
            "ERR_NOT_FOUND", "Method not allowed.", 404
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return response.error_response(err.error_id, err.message, err.http_status)
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected error: %s" % str(err), 400
        )

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
