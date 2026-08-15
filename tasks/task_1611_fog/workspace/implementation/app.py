"""FOG Ordinance Compliance Program API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response
from routes import (
    establishments,
    interceptors,
    inspections,
    violations,
    manifests,
    haulers,
    disposals,
    blockages,
    variances,
    campaigns,
    ops,
)

app = Flask(__name__)

for module in (
    establishments,
    interceptors,
    inspections,
    violations,
    manifests,
    haulers,
    disposals,
    blockages,
    variances,
    campaigns,
    ops,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.status, err.message)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response(ERR_NOT_FOUND, 405, "Method not allowed")


@app.errorhandler(400)
def handle_bad_request(err):
    return error_response(ERR_INVALID_REQUEST, 400, "Malformed request")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", 500, "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
