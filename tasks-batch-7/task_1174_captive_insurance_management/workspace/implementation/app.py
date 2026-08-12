"""Captive Insurance Management API — Flask entry point.

In-memory only; the store starts empty on every boot. Reads $PORT (default
10000) and binds 0.0.0.0.
"""
from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error as error_response
from response import ok
from routes import (
    allocations,
    captives,
    claims,
    collateral,
    filings,
    fronting,
    meetings,
    misc,
    programs,
    reserves,
    statements,
    tax,
    tpa,
    units,
)

app = Flask(__name__)

for module in (
    captives,
    filings,
    programs,
    fronting,
    collateral,
    units,
    allocations,
    claims,
    tpa,
    reserves,
    statements,
    meetings,
    tax,
    misc,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc: ApiError):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return error_response("ERR_INVALID_REQUEST", "Route not found", 400)


@app.errorhandler(405)
def handle_405(exc):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    return error_response("ERR_INVALID_REQUEST", str(exc), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
