"""Nurse Licensure Compact & Credential Expiry API — entry point.

Flask app, error handlers, blueprint registration. The in-memory store starts
empty on every boot; the logical clock defaults to 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask

from errors import ERR_INTERNAL, ERR_NOT_FOUND, ApiError
from response import error_response
from routes import audits, certs, competency, disciplines, evals, licenses, nurses, ops, packets, shifts, units

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (nurses, licenses, certs, disciplines, packets, competency, units, shifts, evals, audits, ops):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(ERR_NOT_FOUND, "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response(ERR_INTERNAL, str(err), 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
