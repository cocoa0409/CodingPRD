import os

from flask import Flask

import response
from errors import ApiError
from routes import (budgets, cycles, poles, tasks, treatments, claims, crews,
                    replacements, audits, snapshots, clock)

app = Flask(__name__)
app.json.sort_keys = False

for module in (budgets, cycles, poles, tasks, treatments, claims, crews,
               replacements, audits, snapshots, clock):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return response.err(e)


@app.errorhandler(404)
def handle_404(e):
    return response.err(ApiError("ERR_NOT_FOUND", 404, "Route not found"))


@app.errorhandler(405)
def handle_405(e):
    return response.err(ApiError("ERR_NOT_FOUND", 405, "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return response.err(e)
    return response.err(ApiError("ERR_INTERNAL", 500, str(e)))


if __name__ == "__main__":
    import errno
    import logging
    import time

    # Per-request access logs add a write on every call; under the 8-round
    # per-test-restart sweep that I/O can stall a request long enough to trip
    # the runner's readiness probe. Errors still surface at WARNING+.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    # The runner SIGKILLs the previous test's server on this port immediately
    # before spawning us; under host contention the old listener can take a
    # moment to release the socket. Retry the bind briefly instead of dying
    # (a dead boot surfaces as a spurious "could not be restarted").
    port = int(os.environ.get("PORT", "10000"))
    deadline = time.monotonic() + 20.0
    while True:
        try:
            app.run(host="0.0.0.0", port=port)
            break
        except OSError as e:
            if e.errno == errno.EADDRINUSE and time.monotonic() < deadline:
                time.sleep(0.1)
                continue
            raise
