"""Non-Revenue Water Loss Reduction API — Flask entry point."""

import os

from flask import Flask

import errors
from errors import ApiError
from response import error_response
from routes import (audit, benchmarks, cases, clock, dmas, leaks, meters,
                    night_flow, pressure, proposals, surveys, water_balance)

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (clock, dmas, water_balance, night_flow, surveys, leaks, meters,
               cases, pressure, proposals, benchmarks, audit):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError(errors.ERR_NOT_FOUND, 404, "resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError(errors.ERR_NOT_FOUND, 404, "resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError(errors.ERR_VALIDATION, 422, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
