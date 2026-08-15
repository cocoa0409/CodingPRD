"""Life Settlement Policy Valuation API — Flask entry point.

In-memory only; the store starts empty on every boot. Listens on $PORT
(default 10000), bound to 0.0.0.0, in the foreground.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from db import REQUEST_LOCK
from errors import ApiError, ERR_NOT_FOUND
from response import err as err_response
from routes import (
    cases,
    clock_routes,
    closing,
    offers,
    portfolios,
    registry,
    tracking,
    valuations,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _acquire():
        REQUEST_LOCK.acquire()

    @app.teardown_request
    def _release(exc):
        if REQUEST_LOCK._is_owned():
            REQUEST_LOCK.release()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return err_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return err_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(HTTPException)
    def _http_error(e):
        return err_response(ERR_NOT_FOUND, e.code or 404, e.description or "error")

    for module in (
        clock_routes,
        registry,
        cases,
        offers,
        closing,
        portfolios,
        tracking,
        valuations,
    ):
        app.register_blueprint(module.bp)

    return app


app = create_app()

if __name__ == "__main__":
    import errno
    import time

    port = int(os.environ.get("PORT", "10000"))
    # The per-test-server harness SIGKILLs the previous server and immediately
    # respawns us on the same port; the killed process's LISTEN socket may not
    # be reaped yet (SO_REUSEADDR does not cover a live LISTEN socket). Retry
    # the bind for up to ~12s so a slow reaper stays inside the harness's
    # 15s readiness poll instead of crashing the boot.
    deadline = time.monotonic() + 12.0
    while True:
        try:
            app.run(host="0.0.0.0", port=port)
            break
        except OSError as e:
            if e.errno == errno.EADDRINUSE and time.monotonic() < deadline:
                time.sleep(0.2)
                continue
            raise
