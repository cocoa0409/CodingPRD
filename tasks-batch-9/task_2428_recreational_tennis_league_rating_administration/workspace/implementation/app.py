"""Recreational Tennis League API — Flask entry point.

State lives only in process memory (see store.py); nothing is seeded at boot.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes_discipline import bp as discipline_bp
from routes_league import bp as league_bp
from routes_match import bp as match_bp
from routes_player import bp as player_bp
from routes_section import bp as section_bp
from routes_team import bp as team_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(section_bp)
    app.register_blueprint(league_bp)
    app.register_blueprint(player_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(match_bp)
    app.register_blueprint(discipline_bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND", "Resource not found."))
        if err.code == 405:
            return error_response(ApiError("ERR_NOT_FOUND", "Resource not found."))
        if err.code in (400, 415):
            return error_response(ApiError("ERR_VALIDATION", "Malformed request."))
        return error_response(ApiError("ERR_VALIDATION", err.description or "Request failed."))

    @app.errorhandler(Exception)
    def _unexpected(err):  # pragma: no cover - defensive
        wrapped = ApiError("ERR_VALIDATION", "Unexpected server error: %s" % err)
        wrapped.http_status = 500
        return error_response(wrapped)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
