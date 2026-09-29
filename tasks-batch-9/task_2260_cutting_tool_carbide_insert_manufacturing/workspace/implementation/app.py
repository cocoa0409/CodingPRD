"""Cutting Tool & Carbide Insert Manufacturing API.

A single Flask process holding all state in memory.  Every boot starts with a
completely empty store and the logical shop clock at its default instant.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import routes
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

routes.register(app)


@app.before_request
def _acquire():
    """One global lock keeps the in-memory store consistent under threading."""
    db.lock.acquire()


@app.teardown_request
def _release(_exc=None):
    try:
        db.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code == 404:
        return error_response("ERR_NOT_FOUND", "No such route.", 404)
    if exc.code == 405:
        return error_response(
            "ERR_NOT_FOUND", "The method is not allowed for this route.", 405
        )
    if exc.code == 400:
        return error_response("ERR_INVALID_REQUEST", "The request is malformed.", 400)
    return error_response(
        "ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500
    )


@app.errorhandler(Exception)
def _unhandled(exc):
    return error_response("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
