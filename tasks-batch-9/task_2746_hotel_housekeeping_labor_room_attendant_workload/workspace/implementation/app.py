"""Hotel Housekeeping Labor & Room Attendant Workload -- Flask application.

Storage is in-memory only and EMPTY on every boot: nothing is seeded, preloaded or
hardcoded.  The logical UTC clock starts at 2026-08-01T00:00:00Z and only ever moves
through POST /_clock/set_current_utc.
"""

import os

from flask import Flask, jsonify

from auth import HOUSEKEEPING_DIRECTOR, authenticate
from envelope import _meta, error_response
from errors import ApiError
from store import STORE
from timeutil import parse_iso_datetime
from validate import read_body, vstr

import routes_assignment
import routes_config
import routes_forecast
import routes_guest
import routes_linen
import routes_roster


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_config.bp)
    app.register_blueprint(routes_forecast.bp)
    app.register_blueprint(routes_roster.bp)
    app.register_blueprint(routes_assignment.bp)
    app.register_blueprint(routes_linen.bp)
    app.register_blueprint(routes_guest.bp)

    @app.post("/_clock/set_current_utc")
    def set_current_utc():
        authenticate((HOUSEKEEPING_DIRECTOR,))
        body = read_body()
        raw = vstr(body, "to_iso8601", 1, None)
        parsed = parse_iso_datetime(raw)
        if parsed is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 UTC instant."
            )
        STORE.set_clock(parsed)
        return jsonify({"meta": _meta(), "response_type": "object", "data": None}), 200

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(
            ApiError("ERR_INVALID_REQUEST", "No such endpoint.", http_status=404)
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(
            ApiError(
                "ERR_INVALID_REQUEST",
                "Method not allowed on this endpoint.",
                http_status=405,
            )
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(
            ApiError("ERR_INVALID_REQUEST", "Unhandled server error: %s" % err, http_status=500)
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
