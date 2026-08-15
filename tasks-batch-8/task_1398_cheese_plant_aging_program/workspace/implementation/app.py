"""Cheese Plant Aging Program API — entry point.

Mounts all route blueprints and installs the envelope error handlers.
The store is purely in-memory and starts empty on every boot.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import (
    additives,
    batches,
    certs,
    clock,
    cutwrap,
    grading,
    make_sheets,
    milk,
    orders,
    plants,
    rooms,
    units,
    vats,
    whey,
)

app = Flask(__name__)

for module in (
    clock,
    plants,
    milk,
    vats,
    additives,
    make_sheets,
    batches,
    whey,
    rooms,
    units,
    grading,
    orders,
    cutwrap,
    certs,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    # Boot robustness under per-test-server isolation: the runner SIGKILLs the
    # previous server on this port and spawns us immediately; if the killed
    # process has not finished releasing its listener yet, bind raises
    # EADDRINUSE. Retry the bind briefly (the killed predecessor always
    # exits, so this converges) instead of dying and surfacing as a spurious
    # "could not be restarted". No SO_REUSEPORT: two live servers must never
    # share the port.
    import time

    from werkzeug.serving import make_server

    port = int(os.environ.get("PORT", "10000"))
    server = None
    for _ in range(200):  # up to ~20s of bind retries
        try:
            server = make_server("0.0.0.0", port, app)
            break
        except OSError:
            time.sleep(0.1)
    if server is None:
        raise SystemExit(f"could not bind port {port}")
    server.serve_forever()
