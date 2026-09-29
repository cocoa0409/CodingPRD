"""FleetCare service-contract API.

A single Flask process holding all state in memory. Every boot starts from a
completely empty store and a logical clock reading 2026-08-01T00:00:00Z.
"""
import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import response  # noqa: E402
from errors import ApiError, ERROR_CATALOG  # noqa: E402
from routes import (  # noqa: E402
    calls,
    clock,
    clubs,
    contracts,
    downtime,
    equipment,
    models,
    parts,
    quotes,
    technicians,
    visits,
)

BLUEPRINTS = (
    clock.bp,
    clubs.bp,
    models.bp,
    equipment.bp,
    contracts.bp,
    quotes.bp,
    technicians.bp,
    visits.bp,
    calls.bp,
    parts.bp,
    downtime.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        code = exc.code or 500
        if code == 404:
            error_id = "ERR_INVALID_REQUEST"
            message = "No endpoint is registered for the requested path"
        elif code in (400, 405, 415):
            error_id = "ERR_INVALID_REQUEST"
            message = exc.description or ERROR_CATALOG[error_id][1]
        else:
            error_id = "ERR_INTERNAL"
            message = exc.description or "Unhandled server error"
        return response.error_response(error_id, message, code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # The envelope is answered even on a defect, never an HTML error page.
        return response.error_response("ERR_INTERNAL", str(exc) or "Unhandled error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
