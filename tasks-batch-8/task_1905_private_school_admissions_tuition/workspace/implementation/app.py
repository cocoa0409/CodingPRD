"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

import errors
from errors import ApiError
from response import error_response
from routes import cycles, registry, applications, evaluations, aid, contracts, reenrollment

app = Flask(__name__)

app.register_blueprint(cycles.bp)
app.register_blueprint(registry.bp)
app.register_blueprint(applications.bp)
app.register_blueprint(evaluations.bp)
app.register_blueprint(aid.bp)
app.register_blueprint(contracts.bp)
app.register_blueprint(reenrollment.bp)


@app.errorhandler(ApiError)
def handle_api_error(e: ApiError):
    return error_response(e)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response(errors.err(errors.ERR_NOT_FOUND, "Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response(errors.err(errors.ERR_NOT_FOUND, "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(e: Exception):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(errors.err(errors.ERR_INVALID_REQUEST, str(e))), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
