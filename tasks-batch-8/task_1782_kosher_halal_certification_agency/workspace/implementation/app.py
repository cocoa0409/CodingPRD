"""Kosher & Halal Certification Agency API — Flask entry point.

Storage is in-memory only; the store starts empty on every boot. The process
listens on 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os
import threading

from flask import Flask, g, request

from errors import ApiError
from middleware import get_context
from response import error as error_response
from routes import BLUEPRINTS

app = Flask(__name__)
app.url_map.strict_slashes = False

# Serialize requests: cascades are atomic within the triggering request.
_lock = threading.RLock()


@app.before_request
def _before_request():
    _lock.acquire()
    g._lock_held = True
    try:
        if request.path.startswith("/api"):
            # Validation priority 1: header presence and role validity.
            get_context()
    except Exception:
        g._lock_held = False
        _lock.release()
        raise


@app.teardown_request
def _teardown_request(exc):
    if getattr(g, "_lock_held", False):
        g._lock_held = False
        _lock.release()


for _bp in BLUEPRINTS:
    app.register_blueprint(_bp, url_prefix="/api")


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_not_found(exc):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_method_not_allowed(exc):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc)
    app.logger.exception(exc)
    return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
