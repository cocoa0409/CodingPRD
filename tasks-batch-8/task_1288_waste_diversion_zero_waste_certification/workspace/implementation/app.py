"""Waste Diversion & Zero-Waste Certification API — Flask entry point."""

import os
import time

from flask import Flask

from db import lock
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response
from routes import (
    applications,
    audits,
    clock,
    contracts,
    events,
    goals,
    periods,
    sites,
    tickets,
    vendors,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(sites.bp)
app.register_blueprint(vendors.bp)
app.register_blueprint(contracts.bp)
app.register_blueprint(tickets.bp)
app.register_blueprint(audits.bp)
app.register_blueprint(events.bp)
app.register_blueprint(goals.bp)
app.register_blueprint(periods.bp)
app.register_blueprint(applications.bp)
app.register_blueprint(clock.bp)


@app.before_request
def _acquire_lock():
    lock.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_e):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(_e):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(400)
def _handle_400(_e):
    return error_response(ApiError(ERR_INVALID_REQUEST, 400, "Bad request"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    # Retry the bind briefly: on shared hosts the runner's per-test restart
    # picks ports from the kernel's ephemeral range, so a transient outbound
    # connection from another process can hold our port as its source socket
    # for a moment (EADDRINUSE). Such blockers clear within seconds; retry
    # under the runner's restart-poll window instead of crashing on first try.
    # NOTE: werkzeug's make_server catches OSError from bind() and raises
    # SystemExit(1), so we must catch SystemExit here, not OSError.
    from werkzeug.serving import make_server

    port = int(os.environ.get("PORT", "10000"))
    deadline = time.monotonic() + 12.0
    httpd = None
    while httpd is None:
        try:
            httpd = make_server("0.0.0.0", port, app, threaded=True)
        except SystemExit:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
    httpd.serve_forever()
