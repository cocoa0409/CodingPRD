"""Network Operations Circuit Fault API — Flask entrypoint.

Storage is entirely in-memory and starts empty on every boot: nothing is
seeded, preloaded or persisted between processes.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import alarms, carriers, circuits, claims, clock, devices, failover
from routes import incidents, orders, paths, reviews, segments, tickets, windows

BLUEPRINTS = (
    carriers.bp,
    circuits.bp,
    devices.bp,
    paths.bp,
    segments.bp,
    alarms.bp,
    incidents.bp,
    tickets.bp,
    claims.bp,
    windows.bp,
    failover.bp,
    orders.bp,
    reviews.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this resource.", 405
            )
        if exc.code and exc.code < 500:
            return error_response(
                "ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400
            )
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
