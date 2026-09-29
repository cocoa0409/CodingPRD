"""Elite Field Purse Admin API — Flask application factory and entry point.

In-memory storage only.  The store is empty on every boot: no seeded entities.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from db import db
from errors import ApiError
from response import error_response
from routes import (
    awards,
    clock_route,
    config,
    doping,
    editions,
    elite_services,
    invitations,
    people,
    results,
)

BLUEPRINTS = (
    editions.bp,
    config.bp,
    people.bp,
    invitations.bp,
    elite_services.bp,
    doping.bp,
    results.bp,
    awards.bp,
    clock_route.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire_lock():
        # One request at a time: every cascade must run to completion before the
        # next reader observes the store (PRD 2.10).
        db.lock.acquire()
        g._db_lock_held = True

    @app.teardown_request
    def _release_lock(_exc=None):
        if g.pop("_db_lock_held", False):
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(_exc):
        return error_response("ERR_INVALID_REQUEST", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(_exc):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
