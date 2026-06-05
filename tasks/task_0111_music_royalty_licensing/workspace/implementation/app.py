"""Music Royalty & Licensing API — Flask entry point.

In-memory store; starts EMPTY on every boot (no seeding). The test harness
restarts this process via start.sh before every test, so all state is wiped.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.catalog import bp as catalog_bp
from routes.usage_events import bp as usage_events_bp
from routes.sync_licenses import bp as sync_licenses_bp
from routes.advances import bp as advances_bp
from routes.statements import bp as statements_bp
from routes.payouts import bp as payouts_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(usage_events_bp)
    app.register_blueprint(sync_licenses_bp)
    app.register_blueprint(advances_bp)
    app.register_blueprint(statements_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_err):
        # Unknown path/resource -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        # Defensive: surface unexpected failures as a 400 invalid-request rather
        # than leaking an HTML 500 (keeps the response envelope consistent).
        return error_response("ERR_INVALID_REQUEST", str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
