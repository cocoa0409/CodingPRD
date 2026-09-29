"""Standards Development Consensus API.

Flask application factory and error envelope wiring. Storage is process-local and
in-memory (see core/store.py); nothing is persisted and nothing is ever seeded,
so a fresh process always starts with twelve empty collections and the logical
clock at exactly 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import envelope
from core.errors import ApiError
from routes import (
    appeals,
    ballots,
    clock,
    comments,
    committees,
    drafts,
    maintenance,
    memberships,
    participants,
    patents,
    public_reviews,
    votes,
    work_items,
)

BLUEPRINTS = (
    participants.bp,
    committees.bp,
    memberships.bp,
    work_items.bp,
    drafts.bp,
    ballots.bp,
    votes.bp,
    public_reviews.bp,
    comments.bp,
    patents.bp,
    appeals.bp,
    maintenance.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "No such endpoint on this API.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "That method is not allowed on this path.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 400:
            return envelope.error_response(
                "ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400)
        return envelope.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
