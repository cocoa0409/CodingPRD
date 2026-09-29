"""Coupon clearinghouse redemption and settlement API.

Entry point: registers every blueprint, installs the request-scoped
all-or-nothing transaction, and renders every failure through the PRD 2.2
error envelope.  The in-memory store starts empty on every boot; nothing is
seeded.
"""

import os

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError
from routes import (
    adjudication,
    clock,
    digital,
    disputes,
    intake,
    offers,
    parties,
    settlement,
)

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for module in (
    parties,
    offers,
    intake,
    adjudication,
    settlement,
    disputes,
    digital,
    clock,
):
    app.register_blueprint(module.bp)


@app.before_request
def _open_transaction():
    db.begin_request()
    g.snapshot = None
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        g.snapshot = db.snapshot()


def _rollback():
    snapshot = g.pop("snapshot", None) if hasattr(g, "snapshot") else None
    if snapshot is not None:
        db.restore(snapshot)


@app.errorhandler(ApiError)
def _handle_api_error(error):
    _rollback()
    return response.error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(error):
    _rollback()
    status = error.code or 500
    if status == 404:
        return response.error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist", 404
        )
    if status == 405:
        return response.error_response(
            "ERR_NOT_FOUND", "The method is not allowed on this resource", 404
        )
    if status == 400:
        return response.error_response(
            "ERR_INVALID_REQUEST", "The request could not be parsed", 400
        )
    return response.error_response(
        "ERR_INVALID_REQUEST", error.description or "Request failed", status
    )


@app.errorhandler(Exception)
def _handle_unexpected(error):
    _rollback()
    return response.error_response("ERR_INTERNAL", str(error), 500)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
