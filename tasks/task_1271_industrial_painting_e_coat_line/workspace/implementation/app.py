"""Entry point: app creation, error handlers, route registration."""
import os
from threading import RLock

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body

app = Flask(__name__, static_folder=None)

# Serialize all requests: keeps multi-entity cascades atomic.
_LOCK = RLock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    _LOCK.release()


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_body(e.error_id, e.http_status, e.message)


@app.errorhandler(HTTPException)
def _handle_http(e):
    if e.code == 404:
        return error_body("ERR_NOT_FOUND", 404, "Resource not found")
    if e.code == 405:
        return error_body("ERR_NOT_FOUND", 404, "Resource not found")
    return error_body("ERR_INVALID_REQUEST", e.code or 400,
                      getattr(e, "description", "Bad request"))


@app.errorhandler(Exception)
def _handle_unexpected(e):
    return error_body("ERR_INTERNAL", 500, "Internal server error: %s" % e)


from routes import bp  # noqa: E402

app.register_blueprint(bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
