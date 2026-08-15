"""Stevedoring Labor Ordering API — entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import routes
from errors import ApiError
from middleware import LOCK, authenticate
from response import error_response

app = Flask(__name__)


@app.before_request
def _before():
    # Serialize requests: keeps OCC races and cascades deterministic.
    LOCK.acquire()
    from flask import g
    g._lock_held = True
    try:
        authenticate()
    except Exception:
        LOCK.release()
        g._lock_held = False
        raise


@app.teardown_request
def _teardown(exc):
    from flask import g
    if getattr(g, "_lock_held", False):
        g._lock_held = False
        LOCK.release()


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _handle_404(e):
    return error_response(errors.not_found("Resource not found"))


@app.errorhandler(405)
def _handle_405(e):
    return error_response(errors.not_found("Method not allowed"))


@app.errorhandler(400)
def _handle_400(e):
    return error_response(errors.validation("Malformed request"))


@app.errorhandler(Exception)
def _handle_generic(e):
    if isinstance(e, HTTPException):
        return error_response(ApiError("ERR_VALIDATION", e.description, e.code or 400))
    return error_response(ApiError("ERR_INTERNAL", "Internal server error", 500))


routes.register(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
