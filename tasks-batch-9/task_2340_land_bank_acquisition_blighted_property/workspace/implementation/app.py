"""County Land Bank Authority API — Flask application entry point.

State lives only in process memory (see db.py) and starts empty on every boot.
"""
import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERROR_STATUS
from response import error_response
from routes import register_routes

app = Flask(__name__)
app.url_map.strict_slashes = False

_LOCK = threading.RLock()


@app.before_request
def _acquire():
    g._touched = set()
    _LOCK.acquire()


@app.teardown_request
def _release(exception=None):
    try:
        _LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return error_response(error.error_id, error.message, error.status)


@app.errorhandler(HTTPException)
def _handle_http_error(error):
    if error.code == 404:
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.",
                              404)
    if error.code == 405:
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "The method is not allowed for this resource.", 405)
    if error.code == 400:
        return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.",
                              400)
    return error_response("ERR_INTERNAL", error.description or "Unexpected error.",
                          error.code or 500)


@app.errorhandler(Exception)
def _handle_unexpected(error):
    return error_response("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)


register_routes(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
