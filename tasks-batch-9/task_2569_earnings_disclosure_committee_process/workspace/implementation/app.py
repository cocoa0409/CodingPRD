"""Earnings Disclosure Committee Process API — entry point.

The store is entirely in-memory and starts EMPTY on every boot: no entity is
seeded, preloaded or hardcoded here. Tests build every precondition through the
declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_cert
import routes_charter
import routes_clock
import routes_cycle
import routes_doc
import routes_event
import routes_filing
from core import ApiError, error_envelope

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for module in (
    routes_charter,
    routes_cycle,
    routes_cert,
    routes_doc,
    routes_event,
    routes_filing,
    routes_clock,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_envelope(exc.error_id, exc.message), exc.http_status


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 404:
        return error_envelope("ERR_NOT_FOUND", "resource not found"), 404
    if exc.code == 405:
        return error_envelope("ERR_NOT_FOUND", "method not allowed for this path"), 404
    if exc.code == 400:
        return error_envelope("ERR_INVALID_REQUEST", "malformed request"), 400
    return (
        error_envelope("ERR_INVALID_REQUEST", exc.description or "request could not be handled"),
        exc.code or 400,
    )


@app.errorhandler(Exception)
def handle_unexpected(exc):  # pragma: no cover - defensive
    return error_envelope("ERR_INVALID_REQUEST", "unexpected server error: %s" % exc), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
