"""Air Ambulance Operations API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding).
Contract (INSTRUCTION.md): bash start.sh runs this module in the foreground,
listening on 0.0.0.0:$PORT (default 10000).
"""

import os

from flask import Flask, jsonify

from core import (
    ApiError, ERR_NOT_FOUND, ERR_VALIDATION, _meta, db, error_response,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

# Serialize requests: cascades must be atomic within a single request.
@app.before_request
def _acquire_lock():
    db.lock.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        db.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _not_found(err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(405)
def _method_not_allowed(err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(Exception)
def _unhandled(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError(ERR_VALIDATION, 400, "Malformed request"))


import routes_admin
import routes_patients
import routes_requests
import routes_missions
import routes_coordination
import routes_billing
import routes_repatriation
import routes_pcr

for module in (
    routes_admin, routes_patients, routes_requests, routes_missions,
    routes_coordination, routes_billing, routes_repatriation, routes_pcr,
):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False)
