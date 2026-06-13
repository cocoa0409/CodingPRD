"""Promotion & Coupon Engine API — entry point and global error handling.

In-memory only: all state lives in db.Store and is wiped on every fresh boot.
No seeding, no persistence, no disk.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response
from routes.blackouts import bp as blackouts_bp
from routes.carts import bp as carts_bp
from routes.clock import bp as clock_bp
from routes.coupons import bp as coupons_bp
from routes.customers import bp as customers_bp
from routes.exclusion_rules import bp as exclusion_rules_bp
from routes.promotions import bp as promotions_bp
from routes.redemptions import bp as redemptions_bp
from routes.segments import bp as segments_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(segments_bp)
    app.register_blueprint(promotions_bp)
    app.register_blueprint(coupons_bp)
    app.register_blueprint(blackouts_bp)
    app.register_blueprint(exclusion_rules_bp)
    app.register_blueprint(carts_bp)
    app.register_blueprint(redemptions_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected failures as a generic 400 invalid-request rather than
        # leaking a stack trace; the envelope stays consistent.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

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
    # would otherwise exit (the runner then sees a dead server and reports
    # "could not be restarted"). Retry the bind for well under the runner's 15s
    # restart window so the reboot is deterministic regardless of host load.
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
