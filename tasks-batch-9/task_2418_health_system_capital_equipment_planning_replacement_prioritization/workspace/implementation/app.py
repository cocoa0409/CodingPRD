"""Health-system capital equipment planning API (Flask, in-memory store).

Boots a completely empty store on every process start — nothing is seeded and
nothing is persisted, so a fresh launch always behaves identically.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from db import db
from errors import ApiError
from response import error_response
from routes import (assets, audits, clock, cycles, estate, gpo, members,
                    projects, requests as requests_routes)

BLUEPRINTS = (
    clock.bp,
    estate.bp,
    cycles.bp,
    assets.bp,
    requests_routes.bp,
    members.bp,
    gpo.bp,
    projects.bp,
    audits.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire():
        # One global lock: every request mutates the shared store atomically.
        db.lock.acquire()
        g._locked = True

    @app.teardown_request
    def _release(exc=None):
        if g.pop("_locked", False):
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed for this path.", 405)
        if exc.code and exc.code >= 500:
            return error_response("ERR_INTERNAL", "Internal server error.", 500)
        return error_response("ERR_VALIDATION",
                              "The request payload failed validation.", 422)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
