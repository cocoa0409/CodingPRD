"""Entry point: app factory, error handlers, route registration.

Storage is in-memory only (Python dicts in db.py); nothing is seeded at
startup — every entity is constructed through the declared API surface.
"""

import os

from errors import ApiError, err_not_found
from response import error_response
from flask import Flask, jsonify

from routes import (
    appeals,
    cancellation_cases,
    clock_routes,
    nonrenewal_cases,
    notices,
    policies,
    policyholders,
    regulatory_reports,
    reinstatement_requests,
    state_profiles,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(clock_routes.bp)
app.register_blueprint(state_profiles.bp)
app.register_blueprint(policyholders.bp)
app.register_blueprint(policies.bp)
app.register_blueprint(cancellation_cases.bp)
app.register_blueprint(nonrenewal_cases.bp)
app.register_blueprint(notices.bp)
app.register_blueprint(reinstatement_requests.bp)
app.register_blueprint(appeals.bp)
app.register_blueprint(regulatory_reports.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(err_not_found())


@app.errorhandler(405)
def handle_405(err):
    return error_response(err_not_found())


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    app.logger.exception("unexpected error")
    body = {
        "meta": {
            "api_request_id": "req_internal",
            "api_request_timestamp": "",
        },
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": "Internal server error"},
    }
    return jsonify(body), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
