"""Ground lease administration service -- Flask entry point.

The store is purely in-memory and starts EMPTY on every boot; nothing is
seeded, preloaded or hardcoded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import auth
import store
import validate as v
from errors import ApiError
from response import error_response, object_response

import routes_setup
import routes_reval
import routes_money
import routes_ops
import routes_reads

PREFIX = "/portfolio"

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_setup.bp, url_prefix=PREFIX)
app.register_blueprint(routes_reval.bp, url_prefix=PREFIX)
app.register_blueprint(routes_money.bp, url_prefix=PREFIX)
app.register_blueprint(routes_ops.bp, url_prefix=PREFIX)
app.register_blueprint(routes_reads.bp, url_prefix=PREFIX)


# ---------------------------------------------------------------------------
# Logical clock (outside the /portfolio mount, per the endpoint table)
# ---------------------------------------------------------------------------
@app.post("/_clock/set_current_utc")
def set_clock():
    auth.require({"LessorAdmin"})
    payload = v.body()
    instant = v.req_dt(payload, "current_utc")
    store.set_now(instant)
    return object_response({"current_utc": store.iso(instant)}, 200)


# ---------------------------------------------------------------------------
# Error handling -- every failure leaves through the documented envelope
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return error_response(
            "ERR_INVALID_REQUEST", "No such resource path.", 404)
    if exc.code == 405:
        return error_response(
            "ERR_INVALID_REQUEST", "Method not allowed for this path.", 405)
    if exc.code in (400, 415):
        return error_response(
            "ERR_INVALID_REQUEST", "The request payload is malformed.", 400)
    return error_response(
        "ERR_INVALID_REQUEST", exc.description or "Request failed.",
        exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
