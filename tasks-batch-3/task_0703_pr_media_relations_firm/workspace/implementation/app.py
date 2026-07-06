"""PR & Media-Relations Firm API — entry point.

Registers all resource blueprints and the global error handlers. Storage is
in-memory only and starts empty on every boot; no entity data is seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response

from routes.clock import bp as clock_bp
from routes.clients import bp as clients_bp
from routes.outlets import bp as outlets_bp
from routes.journalists import bp as journalists_bp
from routes.campaigns import bp as campaigns_bp
from routes.media_lists import bp as media_lists_bp
from routes.pitches import bp as pitches_bp
from routes.press_releases import bp as press_releases_bp
from routes.distributions import bp as distributions_bp
from routes.coverage import bp as coverage_bp
from routes.spokespersons import bp as spokespersons_bp
from routes.interviews import bp as interviews_bp
from routes.retainer_periods import bp as retainer_periods_bp
from routes.time_entries import bp as time_entries_bp
from routes.crisis_events import bp as crisis_events_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp, clients_bp, outlets_bp, journalists_bp, campaigns_bp,
        media_lists_bp, pitches_bp, press_releases_bp, distributions_bp,
        coverage_bp, spokespersons_bp, interviews_bp, retainer_periods_bp,
        time_entries_bp, crisis_events_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map any other werkzeug HTTP error into the standard envelope.
        if e.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        return error_response("ERR_INVALID_REQUEST", e.description or "Bad request",
                              e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
