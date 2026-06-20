"""Hospital Bed Flow API — Flask entry point.

Registers blueprints and the global error handlers that render the standard
error envelope. In-memory storage only; the store starts empty on every boot.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
import errors
from response import error as error_response

from routes.units import bp as units_bp
from routes.encounters import bp as encounters_bp
from routes.bed_requests import bp as bed_requests_bp
from routes.evs_tasks import bp as evs_tasks_bp
from routes.discharge_barriers import bp as discharge_barriers_bp
from routes.surge_events import bp as surge_events_bp
from routes.capacity import bp as capacity_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(units_bp)
    app.register_blueprint(encounters_bp)
    app.register_blueprint(bed_requests_bp)
    app.register_blueprint(evs_tasks_bp)
    app.register_blueprint(discharge_barriers_bp)
    app.register_blueprint(surge_events_bp)
    app.register_blueprint(capacity_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Malformed JSON etc. -> treat as invalid request where reasonable.
        if e.code == 400:
            return error_response(errors.ERR_INVALID_REQUEST, "Bad request", 422)
        return error_response(errors.ERR_INVALID_REQUEST, e.description or "Error", e.code or 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer waitress (a lean pure-Python WSGI server): under the benchmark's
    # per-test-server isolation the server is rebooted before EVERY test, and
    # 8 sweep rounds run concurrently. Waitress binds quickly and emits no
    # dev-server banner or per-request access logging, so the readiness poll
    # is answered with minimal startup work and minimal I/O contention.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, _quiet=True)
    except Exception:
        # Fallback: Flask's built-in server with request logging silenced.
        import logging
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        app.run(host="0.0.0.0", port=port, threaded=True)
