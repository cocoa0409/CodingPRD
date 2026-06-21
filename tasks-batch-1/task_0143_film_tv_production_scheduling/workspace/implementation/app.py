"""Film/TV Production Scheduling API — Flask entry point.

In-memory store, fresh on every boot. No seeding. Registers all route blueprints
and the global error handlers that wrap everything in the standard envelope.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.productions import bp as productions_bp
from routes.schedule import bp as schedule_bp
from routes.crew import bp as crew_bp
from routes.callsheets import bp as callsheets_bp
from routes.locations import bp as locations_bp
from routes.finance import bp as finance_bp
from routes.dailies import bp as dailies_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(productions_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(crew_bp)
    app.register_blueprint(callsheets_bp)
    app.register_blueprint(locations_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(dailies_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on a known path — treat as not found per flat surface.
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Malformed request.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        # Unexpected server error: still wrap in the standard envelope so the
        # response is parseable, but use 500 so genuine bugs stay visible.
        return error_response("ERR_INTERNAL", 500, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    import time

    from werkzeug.serving import make_server

    port = int(os.environ.get("PORT", "10000"))
    # Per-test-server isolation restarts this process before every test, with up
    # to 8 sweeps running concurrently. The prior instance's listening socket may
    # still be in TIME_WAIT when we re-bind the same port, which would otherwise
    # make the process exit immediately with "Address already in use" and surface
    # to the runner as "could not be restarted". werkzeug's make_server sets
    # SO_REUSEADDR; we additionally retry the bind for a short window so a
    # transient collision resolves itself instead of crashing the boot.
    deadline = time.monotonic() + 20.0
    server = None
    while server is None:
        try:
            server = make_server("0.0.0.0", port, app, threaded=True)
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)
    server.serve_forever()
