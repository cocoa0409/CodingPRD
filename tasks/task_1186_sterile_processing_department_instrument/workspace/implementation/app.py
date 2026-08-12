"""Sterile Processing Department API — Flask entry point.

Storage is in-memory only and starts EMPTY on every boot; nothing is seeded.
"""
import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import api_bi
import api_cases
import api_compliance
import api_instruments
import api_iuss
import api_loads
import api_loaners
import api_sterilizers
import api_technicians
import api_templates
import api_trays
from common import ApiError, error_response

app = Flask(__name__)
app.url_map.strict_slashes = False
try:
    app.json.sort_keys = False
except Exception:
    pass

app.register_blueprint(api_templates.bp)
app.register_blueprint(api_trays.bp)
app.register_blueprint(api_instruments.bp)
app.register_blueprint(api_sterilizers.bp)
app.register_blueprint(api_loads.bp)
app.register_blueprint(api_bi.bp)
app.register_blueprint(api_cases.bp)
app.register_blueprint(api_iuss.bp)
app.register_blueprint(api_technicians.bp)
app.register_blueprint(api_loaners.bp)
app.register_blueprint(api_compliance.bp)

# Serialize request handling: the in-memory store is check-then-act in places
# (OCC version checks, capacity checks), and per-test-server isolation means
# race tests may fire concurrent requests at a single server process.
_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()
    g._lock_held = True


@app.teardown_request
def _release_lock(exc=None):
    if getattr(g, "_lock_held", False):
        g._lock_held = False
        _LOCK.release()


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 404:
        return error_response("ERR_NOT_FOUND", 404,
                              "The requested path does not exist.")
    if exc.code == 405:
        return error_response("ERR_METHOD_NOT_ALLOWED", 405,
                              "The method is not allowed for this path.")
    if exc.code and 400 <= exc.code < 500:
        return error_response("ERR_INVALID_REQUEST", 400,
                              exc.description or "Bad request.")
    return error_response("ERR_INTERNAL", 500, "Internal server error.")


@app.errorhandler(Exception)
def handle_unexpected(exc):  # pragma: no cover - safety net
    return error_response("ERR_INTERNAL", 500,
                          "Internal server error: %s" % exc)


@app.after_request
def close_connection(response):
    # werkzeug keep-alive causes intermittent RemoteDisconnected errors under
    # per-test-server isolation; close every connection explicitly.
    response.headers["Connection"] = "close"
    return response


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
