"""Fantasy Football League — Flask API entrypoint.

Boots cleanly from a fresh process. In-memory state only.
"""
import os
import sys

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import APIError
from middleware import authenticate
from response import error_response
from routes.clock import bp as clock_bp
from routes.draft_picks import bp as draft_picks_bp
from routes.leagues import bp as leagues_bp
from routes.matchups import bp as matchups_bp
from routes.players import bp as players_bp
from routes.roster_slots import bp as roster_slots_bp
from routes.teams import bp as teams_bp
from routes.trades import bp as trades_bp
from routes.waiver_claims import bp as waiver_claims_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Avoid Flask's default 308 redirects for trailing slash mismatches —
    # the test harness expects exact-path matching.
    app.url_map.strict_slashes = False
    # Keep JSON keys in insertion order; do not sort.
    app.json.sort_keys = False

    @app.before_request
    def _auth_gate():
        # Allow CORS preflight without auth.
        if request.method == "OPTIONS":
            return None
        # Authenticate every request; raises APIError on failure.
        authenticate()
        return None

    @app.errorhandler(APIError)
    def _handle_api_error(exc: APIError):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def _handle_http(exc: HTTPException):
        # Map common framework errors to our envelope.
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", 404, exc.description or "Not found.")
        if exc.code == 405:
            return error_response("ERR_NOT_FOUND", 404, "Method/path not found.")
        if exc.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST", 400, exc.description or "Bad request.")
        return error_response("ERR_INVALID_REQUEST", exc.code or 400,
                              exc.description or "Error.")

    @app.errorhandler(Exception)
    def _handle_unknown(exc: Exception):
        return error_response("ERR_INVALID_REQUEST", 500, f"Internal error: {exc}")

    app.register_blueprint(leagues_bp)
    app.register_blueprint(teams_bp)
    app.register_blueprint(players_bp)
    app.register_blueprint(draft_picks_bp)
    app.register_blueprint(waiver_claims_bp)
    app.register_blueprint(trades_bp)
    app.register_blueprint(matchups_bp)
    app.register_blueprint(roster_slots_bp)
    app.register_blueprint(clock_bp)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Foreground; bind 0.0.0.0.
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
