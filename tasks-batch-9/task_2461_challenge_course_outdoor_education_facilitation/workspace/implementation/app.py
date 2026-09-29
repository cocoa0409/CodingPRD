"""Challenge Course Ops API — Flask application entry point.

Storage is entirely in-memory (plain dicts in ``db.py``).  Nothing is persisted
to disk and nothing is seeded: a fresh process starts with every collection
empty and the logical clock at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from db import request_lock
from errors import ApiError
from response import error_response

from routes import (blocks, clients, clock, courses, elements, equipment,
                    inspections, observations, participants, staff)

BLUEPRINTS = (
    courses.bp,
    elements.bp,
    inspections.bp,
    staff.bp,
    clients.bp,
    participants.bp,
    blocks.bp,
    equipment.bp,
    observations.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["PROPAGATE_EXCEPTIONS"] = False
    # Emit the envelope in the PRD's declared key order (meta, response_type, data).
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    # The dev server is threaded; serialising requests keeps the cascades and the
    # derived-counter recomputations internally consistent.
    @app.before_request
    def _acquire():
        request_lock.acquire()

    @app.teardown_request
    def _release(exc=None):
        try:
            request_lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested route does not exist.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "The HTTP method is not allowed for this route.", 405)
        if exc.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST", "The request payload is invalid.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_INVALID_REQUEST", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
