"""Self-Serve Event Ticketing & Registration API.

Storage is in-memory only and starts EMPTY on every boot — no entity is
seeded, preloaded or hardcoded at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (
    attendees,
    clock,
    events,
    orders,
    parties,
    payouts,
    promo_codes,
    refund_requests,
    scans,
    seat_blocks,
    ticket_types,
    transfer_requests,
    waitlist,
)

BLUEPRINTS = (
    clock.bp,
    parties.bp,
    events.bp,
    ticket_types.bp,
    seat_blocks.bp,
    promo_codes.bp,
    orders.bp,
    attendees.bp,
    scans.bp,
    refund_requests.bp,
    transfer_requests.bp,
    waitlist.bp,
    payouts.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_EVENT_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 400)
        if exc.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
