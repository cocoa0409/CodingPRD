"""Confined-Space & Rescue-Standby Services API (Flask, in-memory).

The store lives in process memory (db.py) and starts empty on every boot.
A single re-entrant lock serializes request handling so that multi-entity
cascades commit atomically even under concurrent clients.
"""

import os
import threading

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response
from routes import (
    accounts, clock, incidents, permits, personnel, plans, readings, roster,
    spaces, standby, statements, verifications,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

_request_lock = threading.RLock()


@app.before_request
def _acquire_lock():
    _request_lock.acquire()


@app.teardown_request
def _release_lock(exc):
    _request_lock.release()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND[0], "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND[0], "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return error_response(ERR_INVALID_REQUEST[0], str(err), 400)


for module in (clock, personnel, accounts, spaces, plans, permits,
               verifications, roster, readings, standby, incidents,
               statements):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
