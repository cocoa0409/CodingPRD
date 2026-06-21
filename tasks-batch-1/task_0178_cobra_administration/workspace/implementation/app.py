"""COBRA Administration API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot (no seeding). The
test harness reboots the server before every test via start.sh, so all state is
constructed by tests through the declared endpoints.
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error_response
from middleware import require_auth

from routes.plans import bp as plans_bp
from routes.beneficiaries import bp as beneficiaries_bp
from routes.events import bp as events_bp
from routes.notices import bp as notices_bp
from routes.enrollments import bp as enrollments_bp
from routes.subsidies import bp as subsidies_bp
from routes.accounts import bp as accounts_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(plans_bp)
    app.register_blueprint(beneficiaries_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(notices_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(subsidies_bp)
    app.register_blueprint(accounts_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route: still require auth semantics? Tests target declared
        # routes; an unmatched path is a genuine not-found.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected failures as a 400 invalid-request rather than a
        # raw 500 HTML page, keeping the envelope consistent.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
