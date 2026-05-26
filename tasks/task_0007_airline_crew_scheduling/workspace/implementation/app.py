"""Flask app entrypoint. Foreground server bound to 0.0.0.0:$PORT (default 10000)."""
import os

from flask import Flask, request

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, invalid_request
from response import error_response

# Blueprints
from routes.crew_members import bp as crew_bp
from routes.pairings import bp as pairings_bp
from routes.bids import bp as bids_bp
from routes.assignments import bp as assignments_bp
from routes.sick_calls import sick_bp, reserve_bp
from routes.trip_trades import bp as trades_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Preserve key order in JSON output (matches the PRD's envelope shape).
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(crew_bp)
    app.register_blueprint(pairings_bp)
    app.register_blueprint(bids_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(sick_bp)
    app.register_blueprint(reserve_bp)
    app.register_blueprint(trades_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _route_not_found(_e):
        # Unknown route — surface as ERR_NOT_FOUND (PRD §2.9 priority 3 spirit).
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 400)

    @app.errorhandler(400)
    def _bad_request(_e):
        return error_response(ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        # Last-ditch handler: surface as ERR_INVALID_REQUEST 500-safe.
        # We choose 400 over 500 to make schema/parsing issues a single shape.
        # Note: Flask's HTTPException subclasses are handled by the specific
        # handlers above; this only catches truly unexpected errors.
        return error_response(
            ERR_INVALID_REQUEST,
            f"Unhandled server error: {type(exc).__name__}: {exc}",
            500,
        )

    @app.get("/healthz")
    def _healthz():
        return {"ok": True}, 200

    return app


app = create_app()


if __name__ == "__main__":
    import socket
    from werkzeug.serving import ThreadedWSGIServer

    port = int(os.environ.get("PORT", "10000"))

    # Per-test-server isolation restarts this script before every pytest test.
    # When the prior process was killed milliseconds ago the OS may still hold
    # the port in TIME_WAIT, and Werkzeug's default socket would refuse to
    # bind with "Address already in use". Subclass the threaded server and
    # set SO_REUSEADDR + SO_REUSEPORT on the listen socket before the bind.
    class _ReusePortServer(ThreadedWSGIServer):
        def server_bind(self):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except (AttributeError, OSError):
                pass
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            super().server_bind()

    server = _ReusePortServer("0.0.0.0", port, app)
    # Foreground per INSTRUCTION.md — block until SIGTERM/SIGINT.
    server.serve_forever()
