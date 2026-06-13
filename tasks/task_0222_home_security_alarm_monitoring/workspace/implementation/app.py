"""Home Security & Alarm Monitoring API — Flask entry point.

The in-memory store starts EMPTY on every boot (no seeding). All preconditions
are built by the test suite through the declared API surface.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.plans import bp as plans_bp
from routes.accounts import bp as accounts_bp
from routes.systems import bp as systems_bp
from routes.sensors import bp as sensors_bp
from routes.alarm_events import bp as alarm_events_bp
from routes.dispatches import bp as dispatches_bp
from routes.permits import bp as permits_bp
from routes.fines import bp as fines_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(plans_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(systems_bp)
    app.register_blueprint(sensors_bp)
    app.register_blueprint(alarm_events_bp)
    app.register_blueprint(dispatches_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(fines_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource or route not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_VALIDATION", 405, "Method not allowed for this route")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION", 422, "Malformed request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_VALIDATION", 422, "Unexpected error: %s" % str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
