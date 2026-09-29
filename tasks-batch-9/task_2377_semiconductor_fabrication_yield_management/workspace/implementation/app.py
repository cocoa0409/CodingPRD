"""Semiconductor fabrication yield management API (domain: semiconductor-fab-yield).

In-memory only: every process starts with empty collections and a logical clock
pinned to 2026-08-01T00:00:00Z. Nothing is seeded, preloaded or persisted.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import clock
from errors import ApiError
from response import error, ok_raw
from routes import equipment as equipment_routes
from routes import excursions as excursion_routes
from routes import flows as flow_routes
from routes import planning as planning_routes
from routes import production as production_routes
from routes import sort as sort_routes
from validate import body, v_datetime


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(flow_routes.bp)
    app.register_blueprint(equipment_routes.bp)
    app.register_blueprint(planning_routes.bp)
    app.register_blueprint(production_routes.bp)
    app.register_blueprint(excursion_routes.bp)
    app.register_blueprint(sort_routes.bp)

    @app.post("/_clock/set_current_utc")
    def set_current_utc():
        """Test-driving surface; intentionally unauthenticated."""
        data = body()
        moment = v_datetime(data, "to_iso8601")
        clock.set_now(moment)
        from util import iso
        return ok_raw({"current_utc": iso(moment)})

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return error("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)
        if exc.code == 400:
            return error("ERR_VALIDATION", "Malformed request", 400)
        return error("ERR_INTERNAL", exc.description or "Internal error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
