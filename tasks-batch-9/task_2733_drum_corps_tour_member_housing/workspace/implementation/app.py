"""Drum Corps Tour Member Housing & Tuition API.

Storage is in-memory only and starts completely empty on every boot: no entity
is ever seeded, preloaded or hardcoded here.  Tests build all state through the
declared API surface.
"""
import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

from routes import agreements, bookings, clock, contracts, housing, members
from routes import payments, plans, schools, seasons, settlements, staffing
from routes import stops, volunteers

BLUEPRINTS = (
    seasons.bp,
    members.bp,
    contracts.bp,
    plans.bp,
    payments.bp,
    schools.bp,
    agreements.bp,
    housing.bp,
    stops.bp,
    bookings.bp,
    volunteers.bp,
    staffing.bp,
    settlements.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST",
                                  "The requested resource does not exist.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "The HTTP method is not allowed for this path.", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "The request body could not be parsed.", 400)
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "Request could not be processed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
