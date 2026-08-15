"""Entry point: error handlers, route registration.

Post-Production Workflow & Dailies Management API.
All state is in-memory; the store starts empty on every boot.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

import routes.projects
import routes.batches
import routes.assets
import routes.watermark_profiles
import routes.dailies
import routes.bays
import routes.bookings
import routes.turnovers
import routes.vendor_bids
import routes.vendors
import routes.change_lists
import routes.review_rounds
import routes.review_notes
import routes.deliverables
import routes.archive_jobs
import routes.clock_routes

app = Flask(__name__)

for module in (
    routes.projects,
    routes.batches,
    routes.assets,
    routes.watermark_profiles,
    routes.dailies,
    routes.bays,
    routes.bookings,
    routes.turnovers,
    routes.vendor_bids,
    routes.vendors,
    routes.change_lists,
    routes.review_rounds,
    routes.review_notes,
    routes.deliverables,
    routes.archive_jobs,
    routes.clock_routes,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return error_response(ERR_NOT_FOUND, "Referenced entity does not exist", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error_response(
        ERR_INVALID_REQUEST, "Method not allowed for this endpoint", 400
    )


@app.errorhandler(Exception)
def handle_unexpected(exc):
    # Never leak a stack trace as a non-envelope response.
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    return error_response(ERR_INVALID_REQUEST, f"Malformed request: {exc}", 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
