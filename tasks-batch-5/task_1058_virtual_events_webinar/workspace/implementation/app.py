"""Virtual-Events & Webinar Platform API.

Entry point: authentication hook, error handling and route registration.
The in-memory store starts empty on every boot; nothing is ever seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from auth import authenticate
from errors import ApiError
from response import error_response
from routes import (
    booths, broadcasts, clock, events, leads, matches, recordings,
    registrations, session_speakers, sessions, settlements, speakers,
    sponsors, ticket_types, tracks,
)

BLUEPRINTS = (
    clock.bp,
    events.bp,
    ticket_types.bp,
    registrations.bp,
    tracks.bp,
    sessions.bp,
    speakers.bp,
    session_speakers.bp,
    broadcasts.bp,
    recordings.bp,
    sponsors.bp,
    booths.bp,
    leads.bp,
    matches.bp,
    settlements.bp,
)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.before_request
    def _authenticate():
        # Priority 1: runs before anything else the platform does.
        authenticate()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        if exc.code == 404:
            return error_response("ERR_VALIDATION", "Unknown route.", 404)
        if exc.code == 405:
            return error_response("ERR_VALIDATION", "Method not allowed.", 405)
        return error_response("ERR_VALIDATION", exc.description or "Bad request", exc.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_VALIDATION", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
