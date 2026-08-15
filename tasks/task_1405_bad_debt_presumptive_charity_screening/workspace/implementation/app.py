"""Bad Debt & Presumptive Charity Screening API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store is in-memory and starts empty
on every boot; the logical clock starts at 2026-08-01T00:00:00Z (PRD 2.4).
"""

import os

from flask import Flask

from db import db
from errors import ApiError, ERR_NOT_FOUND
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_accounts
    import routes_statements
    import routes_screenings
    import routes_placements
    import routes_disputes
    import routes_plans
    import routes_writeoffs
    import routes_recoveries
    import routes_snapshots
    import routes_clock

    for module in (
        routes_accounts,
        routes_statements,
        routes_screenings,
        routes_placements,
        routes_disputes,
        routes_plans,
        routes_writeoffs,
        routes_recoveries,
        routes_snapshots,
        routes_clock,
    ):
        app.register_blueprint(module.bp)

    @app.before_request
    def _acquire_store_lock():
        db.lock.acquire()

    @app.teardown_request
    def _release_store_lock(exc):
        db.lock.release()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", "internal server error: %s" % err, 500)

    return app


app = create_app()

if __name__ == "__main__":
    import socket
    import time

    from werkzeug.serving import LISTEN_QUEUE, make_server

    port = int(os.environ.get("PORT", "10000"))
    # The runner recycles a fixed port per round: it kill -9s the previous
    # server and immediately respawns this script. On a busy multi-tenant host
    # the port can transiently be held by an unrelated client-side socket in
    # TIME_WAIT (the kernel draws localhost source ports from the same
    # ephemeral range), which blocks bind() even with SO_REUSEADDR for up to
    # the 60s TIME_WAIT linger. app.run()/run_simple() exits the process on
    # the first EADDRINUSE (werkzeug catches OSError and sys.exit(1)s), so the
    # bind is done here with retries past the linger, and the ready socket is
    # handed to make_server via fd=. The process that eventually binds is a
    # fresh boot with empty in-memory state, so per-test isolation semantics
    # are unchanged; a permanent conflict still fails, just after the deadline.
    deadline = time.monotonic() + 75.0
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            sock.listen(LISTEN_QUEUE)
            break
        except OSError:
            sock.close()
            # If the block was not a bare TIME_WAIT but an actual listener —
            # e.g. a sibling instance of this very server spawned by an
            # overlapping restart — the port is served; exit quietly instead
            # of fighting over it.
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    os._exit(0)
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
    server = make_server("0.0.0.0", port, app, threaded=True, fd=sock.fileno())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
