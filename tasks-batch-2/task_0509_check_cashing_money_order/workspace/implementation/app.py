"""Check Cashing & Money Services API — Flask entry point.

In-memory store, logical clock, NO entity seeding at startup. start.sh launches
this in the foreground binding 0.0.0.0:$PORT (default 10000). The store starts
empty on every boot; tests build all preconditions via the declared API."""
import os

from flask import Flask

import errors
from response import error_response

from routes.clock_routes import bp as clock_bp
from routes.customers import bp as customers_bp
from routes.fee_schedules import bp as fee_schedules_bp
from routes.cash_drawers import bp as cash_drawers_bp
from routes.transactions import bp as transactions_bp
from routes.check_items import bp as check_items_bp
from routes.product_children import bp as product_children_bp
from routes.returned_items import bp as returned_items_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(fee_schedules_bp)
    app.register_blueprint(cash_drawers_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(check_items_bp)
    app.register_blueprint(product_children_bp)
    app.register_blueprint(returned_items_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        # Unknown method on a known path -> treat as not found per the contract.
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(errors.ERR_VALIDATION, 422, "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response(errors.ERR_VALIDATION, 422, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    import socket
    import time

    port = int(os.environ.get("PORT", "10000"))

    # Under the 8-round concurrent stability sweep the runner SIGKILLs the prior
    # per-test server and immediately respawns this one on the SAME port. On a
    # loaded host the kernel may not have fully torn down the previous LISTEN
    # socket yet, so a naive app.run() bind can lose the race with EADDRINUSE and
    # exit(1) — which the runner surfaces as "Server process exited prematurely
    # with code 1" / "could not be restarted". Pre-bind our own listening socket
    # with SO_REUSEADDR(+SO_REUSEPORT where available) and retry briefly so a
    # transient rebind race resolves well inside the runner's restart window
    # instead of crashing the boot.
    def _bind_listen_socket(host, prt, deadline_s=12.0):
        start = time.time()
        last_err = None
        while time.time() - start < deadline_s:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            try:
                sock.bind((host, prt))
                sock.listen(128)
                sock.setblocking(True)
                return sock
            except OSError as e:
                last_err = e
                sock.close()
                time.sleep(0.25)
        raise last_err if last_err else OSError("could not bind")

    listen_sock = _bind_listen_socket("0.0.0.0", port)
    # Hand the already-bound socket to Werkzeug (make_server accepts an fd) so it
    # serves on it directly without attempting a second bind.
    from werkzeug.serving import make_server

    server = make_server("0.0.0.0", port, app, threaded=True, fd=listen_sock.fileno())
    server.serve_forever()
