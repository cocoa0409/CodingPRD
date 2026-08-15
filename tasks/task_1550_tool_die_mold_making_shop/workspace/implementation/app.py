"""Tool & Die / Mold Making Shop API — Flask entry point.

Boots with an empty in-memory store; the logical clock starts at exactly
2026-08-01T00:00:00Z. No entity data is seeded at startup.
"""
import os

from flask import Flask

from store import STORE
from helpers import ApiError, error_response
import routes_customers
import routes_designs
import routes_quotes
import routes_jobs
import routes_milestones
import routes_tryout
import routes_eco
import routes_tools
import routes_reservations
import routes_clock


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for module in (routes_customers, routes_designs, routes_quotes, routes_jobs,
                   routes_milestones, routes_tryout, routes_eco, routes_tools,
                   routes_reservations, routes_clock):
        app.register_blueprint(module.bp)

    @app.before_request
    def _acquire_lock():
        STORE.lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        STORE.lock.release()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
