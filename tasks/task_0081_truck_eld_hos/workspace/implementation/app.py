"""Truck ELD HOS API — Flask entry point.

In-memory only. The store (db.py module dicts) starts empty on every boot; no
seeding, no preload. start.sh re-invocation wipes all state by restarting the
process.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response

from routes.drivers import bp as drivers_bp
from routes.vehicles import bp as vehicles_bp
from routes.devices import bp as devices_bp
from routes.duty_events import bp as duty_events_bp
from routes.daily_logs import bp as daily_logs_bp
from routes.violations import bp as violations_bp
from routes.adverse_claims import bp as adverse_claims_bp
from routes.pc_segments import bp as pc_segments_bp
from routes.clock_control import bp as clock_control_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(drivers_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(duty_events_bp)
    app.register_blueprint(daily_logs_bp)
    app.register_blueprint(violations_bp)
    app.register_blueprint(adverse_claims_bp)
    app.register_blueprint(pc_segments_bp)
    app.register_blueprint(clock_control_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return response.error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return response.error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return response.error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return response.error_response(errors.ERR_INVALID_REQUEST, "Bad request.", 400)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        if isinstance(e, errors.ApiError):
            return response.error_response(e.error_id, e.message, e.http_status)
        code = e.code or 500
        if code == 404 or code == 405:
            return response.error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)
        return response.error_response(errors.ERR_INVALID_REQUEST, str(e), 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface unexpected failures as a generic 400 in the standard envelope so
        # tests never see a bare Flask HTML error page.
        return response.error_response(errors.ERR_INVALID_REQUEST,
                                       "Unexpected server error: %s" % str(e), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
