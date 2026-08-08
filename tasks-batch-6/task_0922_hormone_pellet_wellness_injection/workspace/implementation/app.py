"""Hormone-Pellet & Wellness-Injection Clinic API.

Boots with an entirely empty store: no entity is seeded, preloaded or
hardcoded.  Every row the tests need is built through the declared endpoints.
"""
import os
import threading
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes
import store
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

_request_lock = threading.RLock()


@app.before_request
def _before():
    _request_lock.acquire()
    store.begin_request()


@app.teardown_request
def _after(exc=None):
    try:
        _request_lock.release()
    except RuntimeError:  # pragma: no cover - lock was never taken
        pass


@app.errorhandler(ApiError)
def _api_error(exc):
    return envelope.fail(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code == 404:
        return envelope.fail("ERR_VALIDATION", "Unknown route.", 404)
    if exc.code == 405:
        return envelope.fail("ERR_VALIDATION", "Method not allowed.", 405)
    return envelope.fail("ERR_VALIDATION", exc.description or "Request failed.", exc.code or 400)


@app.errorhandler(Exception)
def _unhandled(exc):  # pragma: no cover - defensive
    traceback.print_exc()
    return envelope.fail("ERR_VALIDATION", "Unhandled server error: %s" % exc, 400)


routes.register_all(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
