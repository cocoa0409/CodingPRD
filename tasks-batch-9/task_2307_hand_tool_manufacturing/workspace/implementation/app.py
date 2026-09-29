"""Toolworks hand-tool manufacturing API. In-memory only, empty on every boot."""

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes
from calculations import LineageError
from envelope import err
from errors import ApiError, ERROR_STATUS
from store import LOCK

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

routes.register(app)


# --------------------------------------------------------------------------- #
# one request at a time — keeps the derived ledgers internally consistent
# --------------------------------------------------------------------------- #
@app.before_request
def _acquire():
    LOCK.acquire()


@app.teardown_request
def _release(exc=None):
    try:
        LOCK.release()
    except RuntimeError:
        pass


# --------------------------------------------------------------------------- #
# error handling
# --------------------------------------------------------------------------- #
@app.errorhandler(ApiError)
def _api_error(exc):
    return err(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(LineageError)
def _lineage_error(exc):
    return err(exc.error_id, "SKU lineage is invalid.",
               ERROR_STATUS.get(exc.error_id, 422))


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code == 404:
        return err("ERR_NOT_FOUND", "Resource not found.", 404)
    if exc.code == 405:
        return err("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)
    if exc.code in (400, 415):
        return err("ERR_INVALID_REQUEST", "Malformed request.", 400)
    return err("ERR_INTERNAL", exc.name, exc.code or 500)


@app.errorhandler(Exception)
def _unhandled(exc):
    return err("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)

