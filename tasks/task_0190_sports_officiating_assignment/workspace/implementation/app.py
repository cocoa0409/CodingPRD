"""Sports Officiating Assignment API — Flask entry point.

Registers all blueprints, installs the global error handler that renders the
standard error envelope (PRD §2.2), and runs the server in the foreground on
0.0.0.0:$PORT (default 10000). All state is in-memory (db.py) and wiped on
every fresh boot — nothing is seeded at import time.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.leagues import bp as leagues_bp
from routes.officials import bp as officials_bp
from routes.availabilities import bp as availabilities_bp
from routes.conflicts import bp as conflicts_bp
from routes.games import bp as games_bp
from routes.crew_slots import bp as crew_slots_bp
from routes.assignments import bp as assignments_bp
from routes.appeals import bp as appeals_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(leagues_bp)
    app.register_blueprint(officials_bp)
    app.register_blueprint(availabilities_bp)
    app.register_blueprint(conflicts_bp)
    app.register_blueprint(games_bp)
    app.register_blueprint(crew_slots_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND[0], "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on a known path -> treat as not found per the
        # flat REST surface (no declared method on that resource).
        return error_response(ERR_NOT_FOUND[0], "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(ERR_INVALID_REQUEST[0], "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
