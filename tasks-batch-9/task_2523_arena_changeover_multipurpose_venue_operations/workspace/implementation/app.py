"""Arena Changeover Ops API — Flask application factory and entry point.

State lives entirely in process memory (see store.py). Every fresh process — and
therefore every `bash start.sh` — starts from a completely empty store with the
logical clock parked at 2026-08-01T00:00:00Z. Nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

import routes_booking
import routes_challenge
import routes_clock
import routes_equipment
import routes_ice
import routes_logistics
import routes_order
import routes_venue

BLUEPRINTS = (
    routes_venue.bp,
    routes_equipment.bp,
    routes_ice.bp,
    routes_booking.bp,
    routes_challenge.bp,
    routes_order.bp,
    routes_logistics.bp,
    routes_clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return error_response("ERR_VENUE_NOT_FOUND", "The requested route does not exist.", 404)
        if status == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "The HTTP method is not allowed on this path.", 405)
        if status == 400:
            return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
