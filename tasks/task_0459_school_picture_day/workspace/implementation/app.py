"""School Picture Day API — Flask entry point.

In-memory storage only (db.py module-level dicts). A fresh process wipes all
state. No seeding / preload at startup.
"""
import os

from flask import Flask

from errors import ERROR_STATUS, ApiError
from response import error_response
from routes.clock import bp as clock_bp
from routes.orders import bp as orders_bp
from routes.photos import bp as photos_bp
from routes.retouch import bp as retouch_bp
from routes.roster import bp as roster_bp
from routes.scheduling import bp as scheduling_bp
from routes.sessions import bp as sessions_bp
from routes.shipments import bp as shipments_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(sessions_bp)
    app.register_blueprint(roster_bp)
    app.register_blueprint(scheduling_bp)
    app.register_blueprint(photos_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(retouch_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> generic not found in the standard envelope.
        return error_response("ERR_SESSION_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        # Surface unexpected errors as a generic 422 in the envelope rather than
        # an HTML 500 page, so the harness always sees JSON.
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
