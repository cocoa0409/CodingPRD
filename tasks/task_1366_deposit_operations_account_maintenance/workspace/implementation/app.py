"""Deposit Operations & Account Maintenance API — Flask entry point.

Mounted under /bank. In-memory store; logical clock defaulting to
2026-08-01T00:00:00Z. No entity is seeded at startup — every resource is
built through the API surface.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.json.sort_keys = False

from routes import (  # noqa: E402
    accounts,
    conversions,
    deceased_cases,
    documents,
    garnishments,
    ops,
    signers,
    statement_cycles,
    title_changes,
    transactions,
)

app.register_blueprint(accounts.bp)
app.register_blueprint(transactions.bp)
app.register_blueprint(signers.bp)
app.register_blueprint(documents.bp)
app.register_blueprint(title_changes.bp)
app.register_blueprint(deceased_cases.bp)
app.register_blueprint(garnishments.bp)
app.register_blueprint(statement_cycles.bp)
app.register_blueprint(conversions.bp)
app.register_blueprint(ops.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    from errors import ERR_NOT_FOUND

    return error_response(ApiError(ERR_NOT_FOUND, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    from errors import ERR_NOT_FOUND

    return error_response(ApiError(ERR_NOT_FOUND, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    from errors import ERR_INVALID_REQUEST

    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError(ERR_INVALID_REQUEST, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
