"""Entry point: Flask app, global request lock, error handlers, routes."""

import os

from flask import Flask

import db
from errors import ApiError
from response import error_body

app = Flask(__name__)


@app.before_request
def _acquire_lock():
    # Serialize request handling: every mutation and its cascades are atomic
    # within the request (immediate consistency model).
    db.LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        db.LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(err):
    return error_body(err.error_id, err.message), err.http_status


@app.errorhandler(404)
def _not_found(err):
    return error_body("ERR_NOT_FOUND", "resource not found"), 404


@app.errorhandler(405)
def _method_not_allowed(err):
    return error_body("ERR_NOT_FOUND", "method not allowed"), 405


@app.errorhandler(500)
def _internal_error(err):
    return error_body("ERR_INTERNAL", "internal server error"), 500


from routes import (  # noqa: E402
    programs, pacing_plans, managers, dd_reviews, proposals, commitments,
    calls, distributions, secondary_bids, snapshots, valuation_reports,
    staff, clock,
)

for module in (programs, pacing_plans, managers, dd_reviews, proposals,
               commitments, calls, distributions, secondary_bids, snapshots,
               valuation_reports, staff, clock):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
