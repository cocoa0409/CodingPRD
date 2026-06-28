"""Medical Alert / PERS Monitoring API — entry point.

In-memory only: all state lives in db.store (plain dicts). No persistence, no
seeding at startup. start.sh re-invocation wipes all state by starting a fresh
process. Server reads $PORT (default 10000), binds 0.0.0.0, runs in foreground.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.plans import bp as plans_bp
from routes.subscribers import bp as subscribers_bp
from routes.contracts import bp as contracts_bp
from routes.devices import bp as devices_bp
from routes.contacts import bp as contacts_bp
from routes.alarms import bp as alarms_bp
from routes.returns import bp as returns_bp
from routes.shifts import bp as shifts_bp
from routes.holds import bp as holds_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(subscribers_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(contacts_bp)
    app.register_blueprint(alarms_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(holds_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> standard ERR_NOT_FOUND envelope
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
