"""Jingle & Commercial Music Production API.

Entry point: route registration, the per-request lock that makes every request
atomic, and the error handlers that render the standard envelope.

Storage is in-memory only and starts EMPTY on every boot: nothing is seeded,
preloaded or hardcoded. Every entity is created by clients through the declared
endpoints.
"""

import os
import sys
import threading
import traceback

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.delivery import bp as delivery_bp
from routes.demos import bp as demos_bp
from routes.licensing import bp as licensing_bp
from routes.projects import bp as projects_bp
from routes.reference import bp as reference_bp
from routes.sessions import bp as sessions_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(reference_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(demos_bp)
app.register_blueprint(sessions_bp)
app.register_blueprint(licensing_bp)
app.register_blueprint(delivery_bp)

_request_lock = threading.RLock()


@app.before_request
def _begin_request():
    _request_lock.acquire()
    g._holds_lock = True
    g.touched = set()


@app.teardown_request
def _end_request(exc=None):
    if getattr(g, "_holds_lock", False):
        g._holds_lock = False
        try:
            _request_lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return response.error(err)


@app.errorhandler(404)
def _handle_not_found(err):
    return response.error(ApiError("ERR_NOT_FOUND", "No such resource.", 404))


@app.errorhandler(405)
def _handle_method_not_allowed(err):
    return response.error(ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405))


@app.errorhandler(HTTPException)
def _handle_http_exception(err):
    if err.code == 400:
        return response.error(ApiError("ERR_INVALID_REQUEST", "The request payload is invalid."))
    return response.error(ApiError("ERR_HTTP_ERROR", err.description or "HTTP error.", err.code))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return response.error(err)
    if isinstance(err, HTTPException):
        return _handle_http_exception(err)
    traceback.print_exc(file=sys.stderr)
    return response.error(ApiError("ERR_INTERNAL_ERROR", str(err), 500))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
