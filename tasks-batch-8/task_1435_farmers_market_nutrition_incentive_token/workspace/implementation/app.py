"""Farmers Market Nutrition Incentive API — Flask entrypoint.

In-memory only; the store starts empty on every boot (no seeding). Reads the
PORT env var (default 10000), binds 0.0.0.0, runs in the foreground.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from middleware import IdempotencyReplay
from response import error_response
from routes import (
    clock,
    fraud_cases,
    issuances,
    market_days,
    markets,
    programs,
    settlement_runs,
    shoppers,
    submissions,
    token_batches,
    tokens,
    vendors,
)

app = Flask(__name__)

for module in (
    clock,
    programs,
    markets,
    vendors,
    shoppers,
    market_days,
    token_batches,
    issuances,
    tokens,
    submissions,
    fraud_cases,
    settlement_runs,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc)


@app.errorhandler(IdempotencyReplay)
def handle_replay(exc):
    from flask import jsonify
    return jsonify(exc.body), exc.status


@app.errorhandler(404)
def handle_404(_exc):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource does not exist"))


@app.errorhandler(405)
def handle_405(_exc):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource does not exist"))


@app.errorhandler(Exception)
def handle_unexpected(exc):
    # Never leak a bare 500 HTML page; keep the error envelope contract.
    if isinstance(exc, (ApiError, IdempotencyReplay)):
        raise exc
    app.logger.exception("unexpected error")
    return error_response(ApiError("ERR_INTERNAL", 500, str(exc)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
