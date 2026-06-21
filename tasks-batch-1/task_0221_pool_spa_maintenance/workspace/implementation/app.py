"""Pool & Spa Maintenance API — entry point and global error handling.

In-memory only: all state lives in db.Store and is wiped on every fresh boot.
No seeding, no persistence, no disk.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response
from routes.customers import bp as customers_bp
from routes.invoices import bp as invoices_bp
from routes.pools import bp as pools_bp
from routes.route_assignments import bp as routes_bp
from routes.seasonal_events import bp as seasonal_events_bp
from routes.service_plans import bp as service_plans_bp
from routes.visits import bp as visits_bp
from routes.work_orders import bp as work_orders_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(pools_bp)
    app.register_blueprint(service_plans_bp)
    app.register_blueprint(routes_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(seasonal_events_bp)
    app.register_blueprint(invoices_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        # An unknown method on a known path is closest to a not-found route.
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        # Surface unexpected failures as a generic invalid-request rather than
        # leaking a stack trace; the envelope stays consistent.
        return error_response("ERR_INVALID_REQUEST", str(exc), 422)

    return app


app = create_app()


if __name__ == "__main__":
    import time

    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress (a production WSGI server with a real thread pool and a
    # generous listen backlog) rather than Flask's single-accept-thread dev
    # server. Under per-test-server isolation with 8 rounds booting concurrently,
    # the dev server intermittently refuses mid-test connections; waitress
    # accepts them reliably.
    #
    # Bind-retry loop: the runner restarts this server before every test by
    # SIGKILL-ing the previous process and immediately re-spawning start.sh.
    # Under concurrent load the SIGKILL'd socket can still be in a transitional
    # state, so an immediate bind raises "Address already in use" and waitress
    # would otherwise exit. Retry the bind for well under the runner's restart
    # window so the reboot is deterministic regardless of host load.
    from waitress import create_server

    deadline = time.time() + 12.0
    server = None
    while True:
        try:
            server = create_server(app, host="0.0.0.0", port=port, threads=8, backlog=128)
            break
        except OSError:
            if time.time() >= deadline:
                raise
            time.sleep(0.2)
    server.run()
