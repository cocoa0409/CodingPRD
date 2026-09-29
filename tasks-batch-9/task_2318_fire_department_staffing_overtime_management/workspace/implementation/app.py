"""Fire Staffing & Overtime API - Flask entry point.

Storage is in-memory only (see store.py); the process comes up with an empty
store on every boot and nothing is ever seeded.
"""

import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes
from envelope import error_response
from errors import ApiError
from store import db

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

_request_lock = threading.RLock()

routes.register(app)


@app.before_request
def _begin_request():
    _request_lock.acquire()
    g._holds_lock = True
    db.begin()


@app.teardown_request
def _end_request(_exception=None):
    if g.pop("_holds_lock", False):
        try:
            _request_lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(error):
    status = error.code or 500
    if status == 404:
        error_id = "ERR_RESOURCE_NOT_FOUND"
    elif status == 401:
        error_id = "ERR_UNAUTHENTICATED"
    elif status == 403:
        error_id = "ERR_FORBIDDEN_ROLE"
    else:
        error_id = "ERR_INVALID_REQUEST"
        status = 400 if status in (400, 405, 415) else status
    return error_response(error_id, error.description or error_id, status)


@app.errorhandler(Exception)
def _handle_unexpected(error):
    return error_response("ERR_INVALID_REQUEST", str(error) or "Unhandled error.", 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False, debug=False)
