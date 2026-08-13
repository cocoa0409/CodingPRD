"""Salary Survey Market Pricing API — entry point."""
import os

from flask import Flask

from common import ApiError, error_response
from lifecycle import tick
import routes_core
import routes_vendor
import routes_flow
import routes_pricing

app = Flask(__name__)
app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_vendor.bp)
app.register_blueprint(routes_flow.bp)
app.register_blueprint(routes_pricing.bp)


@app.before_request
def _logical_clock_sweep():
    # Automatic system transitions (vendor expiry, survey auto-close) are
    # evaluated against the logical clock on every request.
    tick()


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _handle_404(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(e):
    return error_response(ApiError("ERR_NOT_FOUND", 405, "Method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INTERNAL", 500, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
