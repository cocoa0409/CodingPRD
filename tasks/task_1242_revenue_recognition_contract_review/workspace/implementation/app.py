"""Entry point: Flask app, error handlers, request serialization, route registration."""
import os
import threading

from flask import Flask, g

from db import commit_dirty, discard_dirty
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import err_response

app = Flask(__name__)
app.url_map.strict_slashes = False

_lock = threading.RLock()


@app.before_request
def _acquire():
    _lock.acquire()


@app.after_request
def _commit(response):
    try:
        if response.status_code < 400:
            commit_dirty()
        else:
            discard_dirty()
    finally:
        _lock.release()
    return response


@app.teardown_request
def _release(exc):
    if _lock._is_owned():
        try:
            _lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _api_error(e):
    return err_response(e.error_id, e.message, e.status)


@app.errorhandler(404)
def _not_found(e):
    return err_response(ERR_NOT_FOUND, "Path id does not identify an existing resource", 404)


@app.errorhandler(405)
def _method_not_allowed(e):
    return err_response(ERR_INVALID_REQUEST, "Method not allowed on this path", 405)


@app.errorhandler(Exception)
def _internal(e):
    if isinstance(e, ApiError):
        return err_response(e.error_id, e.message, e.status)
    return err_response("ERR_INTERNAL", str(e), 500)


from routes import ALL_BLUEPRINTS  # noqa: E402

for _bp in ALL_BLUEPRINTS:
    app.register_blueprint(_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
