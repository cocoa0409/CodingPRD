"""Cruise Revenue Management & Cabin Inventory API.

All state lives in module-level dicts inside store.py: nothing is written to
disk and nothing is seeded at import time, so every process starts empty.
"""

import os

from flask import Flask

import shape
import store
from auth import ALL_ROLES, actor
from envelope import error_response, object_response
from errors import DEFAULT_MESSAGES, ERROR_HTTP, ApiError
import routes_bids
import routes_bookings
import routes_catalog
import routes_groups
import routes_guests
import routes_itinerary
import routes_promotions
import routes_sailings

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(routes_sailings.bp)
app.register_blueprint(routes_catalog.bp)
app.register_blueprint(routes_promotions.bp)
app.register_blueprint(routes_groups.bp)
app.register_blueprint(routes_guests.bp)
app.register_blueprint(routes_bookings.bp)
app.register_blueprint(routes_bids.bp)
app.register_blueprint(routes_itinerary.bp)


# --------------------------------------------------------------------------
# Test-driving: the logical clock (PRD 2.4)
# --------------------------------------------------------------------------
@app.post("/_clock/set_current_utc")
def set_current_utc():
    actor(*ALL_ROLES)
    data = shape.body()
    moment = shape.req_dt(data, "to_iso8601")
    # Moving time mutates no entity and increments no version.
    store.set_clock(moment)
    return object_response({})


# --------------------------------------------------------------------------
# Error rendering (PRD 2.2)
# --------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    return error_response(
        "ERR_ROUTE_NOT_FOUND", "No such route.", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return error_response(
        "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this route.", 405)


@app.errorhandler(400)
def handle_400(_exc):
    return error_response(
        "ERR_INVALID_REQUEST",
        DEFAULT_MESSAGES.get("ERR_INVALID_REQUEST", "Malformed request."),
        ERROR_HTTP.get("ERR_INVALID_REQUEST", 400))


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    app.logger.exception("unhandled error: %s", exc)
    return error_response("ERR_INTERNAL", "Internal server error.", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
