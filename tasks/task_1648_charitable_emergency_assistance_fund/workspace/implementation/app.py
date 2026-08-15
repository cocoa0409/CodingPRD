"""Charitable Emergency Assistance Fund API — entry point.

Flask app wiring: blueprints, error handlers, 404/405 fallbacks.
Storage is in-memory only; the store starts empty on every boot.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response
import routes_admin
import routes_cases
import routes_money

app = Flask(__name__)
app.json.sort_keys = False

app.register_blueprint(routes_admin.bp)
app.register_blueprint(routes_cases.bp)
app.register_blueprint(routes_money.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(400)
def handle_400(err):
    # Malformed JSON etc.
    return error_response(ApiError(ERR_INVALID_REQUEST, 400,
                                   "Request body is not well-formed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError(ERR_INVALID_REQUEST, 400, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
