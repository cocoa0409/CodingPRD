"""Trade Order Allocation API — Flask entrypoint.

In-memory only: all state lives in db.py module dicts; every fresh process
boots with an empty store (no seeding, no files, no external persistence).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error_response
from routes import blocks, budgets, corrections, misc, orders, plans, refdata, restrictions, settlement

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for bp in (refdata.bp, budgets.bp, restrictions.bp, orders.bp, blocks.bp,
           plans.bp, corrections.bp, settlement.bp, misc.bp):
    app.register_blueprint(bp)


@app.before_request
def _acquire_lock():
    db.LOCK.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        db.LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(HTTPException)
def _handle_http(err):
    # unmatched route / wrong method / malformed request — still envelope-shaped
    error_id = "ERR_NOT_FOUND" if err.code == 404 else (
        "ERR_METHOD_NOT_ALLOWED" if err.code == 405 else "ERR_INVALID_REQUEST")
    status = err.code if err.code and 400 <= err.code < 600 else 500
    return error_response(error_id, status, err.description or err.name)


@app.errorhandler(Exception)
def _handle_unexpected(err):
    return error_response("ERR_INTERNAL", 500, str(err))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
