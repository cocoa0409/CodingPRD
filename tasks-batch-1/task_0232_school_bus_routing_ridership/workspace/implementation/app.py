"""School Bus Routing & Ridership API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No seeding.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body
from db import LOCK

from routes.districts import bp as districts_bp
from routes.routes_rt import bp as routes_bp
from routes.stops import bp as stops_bp
from routes.students import bp as students_bp
from routes.applications import bp as applications_bp
from routes.drivers import bp as drivers_bp
from routes.assignments import bp as assignments_bp
from routes.bus_trips import bp as bus_trips_bp
from routes.taps import bp as taps_bp
from routes.notifications import bp as notifications_bp
from routes.missed_bus import bp as missed_bus_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        districts_bp, routes_bp, stops_bp, students_bp, applications_bp,
        drivers_bp, assignments_bp, bus_trips_bp, taps_bp, notifications_bp,
        missed_bus_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    # Serialize all handlers so each request runs atomically.
    @app.before_request
    def _acquire():
        LOCK.acquire()

    @app.teardown_request
    def _release(exc):
        try:
            LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def _handle_404(e):
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def _handle_405(e):
        return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed")), 404

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return jsonify(error_body(e.error_id, e.message)), e.http_status
        return jsonify(error_body("ERR_INTERNAL", str(e))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve with waitress (a robust WSGI server with a real connection queue)
    # rather than werkzeug's dev server, which under heavy concurrent
    # connection churn (the 8-round per-test-restart sweep) intermittently
    # drops connections and surfaces client-side BadStatusLine errors. Fall
    # back to the dev server only if waitress is unavailable.
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=8, _quiet=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
