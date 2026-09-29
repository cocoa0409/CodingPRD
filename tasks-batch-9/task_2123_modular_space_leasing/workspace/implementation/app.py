"""Modular Space Leasing API — entry point.

The in-memory store starts EMPTY on every boot; no entity is ever seeded here.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError, ERROR_STATUS
from response import error_response
from routes import register_all

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

register_all(app)


@app.before_request
def _acquire_lock():
    db.lock.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        db.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_exception(exc):
    if exc.code == 404:
        return error_response("ERR_INVALID_REQUEST", "The requested route does not exist.", 404)
    if exc.code == 405:
        return error_response("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)
    if exc.code in (400, 415):
        return error_response("ERR_INVALID_REQUEST", "The request body is invalid.", 422)
    return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 400)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    app.logger.exception("Unhandled error: %s", exc)
    return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
