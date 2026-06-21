"""Retail Checking & Savings API — Flask entry point.

In-memory only. Fresh process => empty store. No seeding at startup.
"""
import os

from flask import Flask

from errors import ApiError
import errors
from response import error_response

from routes.clock import bp as clock_bp
from routes.apy_tiers import bp as apy_tiers_bp
from routes.customers import bp as customers_bp
from routes.applications import bp as applications_bp
from routes.accounts import bp as accounts_bp
from routes.owners import bp as owners_bp
from routes.transactions import bp as transactions_bp
from routes.stop_payments import bp as stop_payments_bp
from routes.reads import bp as reads_bp
from routes.ach import bp as ach_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(apy_tiers_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(owners_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(stop_payments_bp)
    app.register_blueprint(reads_bp)
    app.register_blueprint(ach_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        # Method not allowed on a known path => treat as not-found resource.
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress (production WSGI server) rather than Werkzeug's dev
    # server: under the benchmark's per-test-server isolation the server is
    # rebooted before every test with 8 sweep rounds running concurrently. The
    # Werkzeug dev server intermittently drops freshly-accepted connections under
    # that load; waitress's larger backlog and worker pool serve them reliably.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, backlog=256)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
