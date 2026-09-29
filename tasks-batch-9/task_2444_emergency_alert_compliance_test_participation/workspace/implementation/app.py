"""EAS Compliance API — application factory and entrypoint.

Storage is in-memory only and starts completely empty on every fresh process:
no entity is ever seeded, preloaded or hardcoded (the tests build every
precondition through the declared endpoints).
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import (
    alerts,
    assignments,
    clock_routes,
    devices,
    filings,
    inspections,
    log_entries,
    outages,
    relay_rules,
    state_plans,
    stations,
    test_events,
    wea_notices,
)

BLUEPRINTS = (
    clock_routes.bp,
    state_plans.bp,
    stations.bp,
    relay_rules.bp,
    devices.bp,
    assignments.bp,
    outages.bp,
    alerts.bp,
    wea_notices.bp,
    test_events.bp,
    log_entries.bp,
    filings.bp,
    inspections.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.before_request
    def _init_request_state():
        g.touched_rows = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "The method is not allowed for this resource.", 405
            )
        if exc.code == 401:
            return error_response(
                "ERR_MISSING_AUTH_HEADERS", "Authentication headers are required.", 401
            )
        if exc.code == 403:
            return error_response("ERR_UNAUTHORIZED", "Not authorised.", 403)
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Invalid request.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
