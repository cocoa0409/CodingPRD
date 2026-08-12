"""Entry point: Flask app, error handlers, blueprint registration.

In-memory only — the store starts empty on every boot; nothing is seeded.
"""
import os

from flask import Flask

import db  # noqa: F401  (module init creates the empty store)
import services as svc
from errors import ApiError
from response import error_response
from routes import (
    absences, assignments, buildings, clock, coverage, evaluations, funding,
    paras, plans, scos, students, timesheets,
)

app = Flask(__name__)

for module in (clock, plans, buildings, students, scos, paras, assignments,
               coverage, absences, timesheets, evaluations, funding):
    app.register_blueprint(module.bp)


@app.before_request
def _lazy_qualification_expiry_sweep():
    """Lazy qualification-expiry cascade (PRD §2.4/§3.3): observes the logical
    clock on subsequent reads/writes rather than at the moment the clock moves."""
    from flask import request
    if request.path.startswith("/sped-staffing/"):
        svc.lazy_expiry_sweep()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", 500, "internal error: %s" % err)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
