"""Public Pension Administration API — Flask entry point.

Mounts all route blueprints under "/" and renders every error through the
standard envelope. The store starts empty on every boot; the logical clock
reads exactly 2026-08-01T00:00:00Z until a FundAdmin sets it.
"""

import os
import traceback

from flask import Flask

from errors import ApiError
from response import error
from routes import (
    clock_routes,
    funds,
    employers,
    members,
    contributions,
    purchases,
    retirement,
    disability,
    benefits,
    beneficiaries,
)

app = Flask(__name__)

for bp in (
    clock_routes.bp,
    funds.bp,
    employers.bp,
    members.bp,
    contributions.bp,
    purchases.bp,
    retirement.bp,
    disability.bp,
    benefits.bp,
    beneficiaries.bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_404(exc):
    return error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(exc):
    return error("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    traceback.print_exc()
    return error("ERR_INTERNAL", 500, "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
