"""Closet & Garage Organization API — Flask entry point.

In-memory only. State starts empty on every boot; no seeding. The test harness
restarts this process (via start.sh) before every test, which wipes all state.
"""
import logging
import os

from flask import Flask, request

from errors import ApiError, ERRORS
from response import error_response

# Silence werkzeug's per-request access log. Under the per-test-server isolation
# the harness reboots this process before every test (8 rounds concurrently),
# so hundreds of boots overlap; quiet logging keeps boot light and avoids the
# flaky "could not be restarted" health-check timeouts caused by log contention.
logging.getLogger("werkzeug").setLevel(logging.ERROR)

from routes.customers import bp as customers_bp
from routes.design import bp as design_bp
from routes.quotes import bp as quotes_bp
from routes.deposits import bp as deposits_bp
from routes.installs import bp as installs_bp
from routes.change_orders import bp as change_orders_bp
from routes.warranty import bp as warranty_bp
from routes.financing import bp as financing_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(design_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(deposits_bp)
    app.register_blueprint(installs_bp)
    app.register_blueprint(change_orders_bp)
    app.register_blueprint(warranty_bp)
    app.register_blueprint(financing_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e: ApiError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route. Distinguish from resource-not-found by message only.
        return error_response("ERR_RESOURCE_NOT_FOUND", "Route not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface anything unexpected as a 422 validation-style error rather
        # than a bare HTML 500, so the test harness always gets JSON.
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_VALIDATION", str(e), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Disable the reloader/debugger and the dev-server banner so boot is fast and
    # single-process; threaded=True keeps concurrent requests from serializing.
    try:
        import werkzeug.serving as _ws
        _ws._log = lambda *a, **k: None  # suppress werkzeug startup banner output
    except Exception:
        pass
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
