"""Pallet Recycling API -- Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). All state is in-memory and starts empty
on every boot; the logical clock starts at exactly 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask

from errors import ApiError
from response import error

from routes import specs, indices, cores, repairs, lots, customers, orders, pool_returns, routes, grinding, clock


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        specs, indices, cores, repairs, lots, customers, orders,
        pool_returns, routes, grinding, clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a bare 500 HTML page; surface as a 400 envelope.
        if isinstance(err, ApiError):
            return error(err.error_id, err.message, err.http_status)
        return error("ERR_INVALID_REQUEST", "Malformed request: %s" % err, 400)

    return app


app = create_app()

if __name__ == "__main__":
    import socket
    import struct
    import time

    from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler

    class _Handler(WSGIRequestHandler):
        def setup(self):
            # Abortive close (SO_LINGER l_onoff=1, l_linger=0) for every
            # accepted connection. The per-test harness SIGKILLs this server
            # and immediately spawns a replacement on the same port; the
            # kernel's orderly close of the killed server's accepted sockets
            # leaves server-side TIME_WAIT entries that, on this kernel, block
            # the replacement's rebind for up to 60s despite SO_REUSEADDR.
            # With linger=0, close becomes an RST and no TIME_WAIT is created.
            # Safe here because this server is keep-alive-only and never
            # closes a connection itself while a response is in flight --
            # closes happen only on process kill (idle sockets, no data
            # pending) or after the client has already closed.
            self.request.setsockopt(
                socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            super().setup()

    class _Server(BaseWSGIServer):
        multithread = True

    port = int(os.environ.get("PORT", "10000"))
    # Bounded retry on EADDRINUSE (werkzeug raises SystemExit(1)) covers the
    # residual race where an unrelated process grabs the port in the
    # kill-and-respawn gap.
    deadline = time.monotonic() + 13.0
    while True:
        try:
            _Server("0.0.0.0", port, app, handler=_Handler).serve_forever()
            break
        except SystemExit:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.3)
