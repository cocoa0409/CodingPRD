"""SaaS Subscription Billing API — Flask entry point.

In-memory only: all state lives in db.py module-level dicts and is wiped on each
process boot. No entity is seeded, preloaded, or hardcoded at startup.
"""
import os

from flask import Flask

import errors
from response import error as error_response
from routes.catalogue import bp as catalogue_bp
from routes.accounts import bp as accounts_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.invoices import bp as invoices_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalogue_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown path -> ERR_NOT_FOUND envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected failures as a generic invalid-request envelope so the
        # response is always well-formed JSON. Re-raise ApiError handled above.
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response(errors.ERR_INVALID_REQUEST, str(exc), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Build Werkzeug's server directly so we can enlarge the listen backlog.
    # Under the 8x-concurrent per-test-server sweep, the default backlog can be
    # exhausted between the runner's readiness probe and the test's first
    # request, surfacing as a transport-level BadStatusLine / connection reset.
    # A larger request_queue_size keeps queued connections from being dropped.
    from werkzeug.serving import make_server

    httpd = make_server("0.0.0.0", port, app, threaded=True)
    # make_server already called listen() with the default backlog; re-issue
    # listen() with a larger backlog so queued connections aren't dropped.
    httpd.request_queue_size = 128
    httpd.socket.listen(128)
    httpd.serve_forever()
