"""Museum & Zoo Membership & Admission API — Flask entry point.

In-memory store (db.py) starts EMPTY on every boot; no seeding. The test harness
restarts this process before every test (per-test-server isolation).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
import response
from routes.catalog import bp as catalog_bp
from routes.memberships import bp as memberships_bp
from routes.orders import bp as orders_bp
from routes.jobs import bp as jobs_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(jobs_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / path: treat as resource-not-found semantics.
        return response.error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        # Bad JSON, etc. -> map to a structured error.
        status = exc.code or 500
        if status == 400:
            return response.error("ERR_INVALID_REQUEST", "Malformed request", 422)
        return response.error("ERR_INVALID_REQUEST", str(exc), status if status >= 400 else 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
