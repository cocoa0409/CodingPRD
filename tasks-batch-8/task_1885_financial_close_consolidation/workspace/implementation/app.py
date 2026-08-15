"""Financial Close & Consolidation API — entry point.

In-memory Flask implementation. The store starts empty on every boot; all
time-dependent behavior reads the server-side logical clock (default
2026-08-01T00:00:00Z), never the host wall clock.
"""
import os

from flask import Flask

from core import ApiError, bp, error_response

# Route modules register on the shared blueprint at import time.
import routes_periods  # noqa: F401
import routes_work  # noqa: F401
import routes_ledger  # noqa: F401

app = Flask(__name__)
app.register_blueprint(bp)


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
