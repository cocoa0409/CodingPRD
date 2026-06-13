"""Junk Removal & Hauling API — Flask entry point.

In-memory store only; empty on every boot (no seeding). Registers blueprints and
the standard error/response envelope handlers.
"""
import os
from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
import response
from routes.config import bp as config_bp
from routes.haul_jobs import bp as haul_jobs_bp
from routes.dispatches import bp as dispatches_bp
from routes.invoices import bp as invoices_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(haul_jobs_bp)
    app.register_blueprint(dispatches_bp)
    app.register_blueprint(invoices_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> generic not-found in the standard envelope.
        return response.error("ERR_JOB_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return response.error("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        return response.error("ERR_INVALID_REQUEST", e.description or "HTTP error",
                              e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Fail closed in the standard envelope rather than leaking a stack trace.
        return response.error("ERR_INVALID_REQUEST", "Internal error: %s" % str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer waitress: the Werkzeug dev server's keep-alive handling races with the
    # test client's pooled requests.Session under per-test-server isolation, producing
    # intermittent BadStatusLine connection resets. Waitress handles concurrent
    # keep-alive connections reliably. Fall back to the dev server if unavailable.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
