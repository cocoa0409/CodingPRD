"""Pet DNA & Health Screening API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No seeding.
"""
import logging
import os

from flask import Flask, jsonify

# Silence Werkzeug's per-request access log. Under the per-test-server harness
# the readiness probe hammers the boot endpoint with hundreds of requests; the
# resulting log flood adds avoidable CPU/IO contention when 8 rounds boot
# concurrently and can push a slow boot past the restart window. No behaviour
# change — only logging is suppressed.
logging.getLogger("werkzeug").setLevel(logging.ERROR)

from errors import ApiError
from response import error_response

from routes.clock_routes import clock_bp
from routes.accounts import accounts_bp
from routes.pets import pets_bp
from routes.kits import kits_bp
from routes.samples import samples_bp
from routes.reports import reports_bp
from routes.share_links import share_links_bp
from routes.relative_matches import relative_matches_bp
from routes.subscriptions import subscriptions_bp
from routes.data_requests import data_requests_bp
from routes.marker_catalog import marker_catalog_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(pets_bp)
    app.register_blueprint(kits_bp)
    app.register_blueprint(samples_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(share_links_bp)
    app.register_blueprint(relative_matches_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(data_requests_bp)
    app.register_blueprint(marker_catalog_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(
            ApiError("ERR_INVALID_REQUEST", 422, "Malformed request")
        )

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(
            ApiError("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % str(e))
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Suppress the dev-server startup banner to shave a little boot I/O.
    import flask.cli
    flask.cli.show_server_banner = lambda *a, **k: None
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
