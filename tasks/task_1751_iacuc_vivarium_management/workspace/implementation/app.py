"""IACUC & Vivarium Management API — Flask entry point.

Boots with an empty in-memory store and the logical clock at
2026-08-01T00:00:00Z. Reads PORT (default 10000) and binds 0.0.0.0.
"""
import os

from flask import Flask

from envelope import err_response
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST

app = Flask(__name__)

import routes_admin
import routes_protocols
import routes_vivarium
import routes_billing
import routes_compliance

app.register_blueprint(routes_admin.bp)
app.register_blueprint(routes_protocols.bp)
app.register_blueprint(routes_vivarium.bp)
app.register_blueprint(routes_billing.bp)
app.register_blueprint(routes_compliance.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return err_response(err)


@app.errorhandler(404)
def handle_404(err):
    return err_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return err_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(400)
def handle_400(err):
    return err_response(ApiError(ERR_INVALID_REQUEST, 400, "Malformed request"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return err_response(ApiError(ERR_INVALID_REQUEST, 400, str(err)))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
