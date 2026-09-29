"""Teaching Artist Residencies API — Flask application entry point.

Storage is in-memory only and starts completely empty on every boot; no entity
data is ever seeded, preloaded or persisted to disk.
"""
import os

from flask import Flask, g

import db
import response
from errors import ApiError
from routes import (
    artists,
    clock_route,
    lesson_plans,
    reports,
    residencies,
    schools,
    sessions,
    standards,
    vouchers,
)

BLUEPRINTS = (
    schools.bp,
    artists.bp,
    standards.bp,
    residencies.bp,
    lesson_plans.bp,
    sessions.bp,
    vouchers.bp,
    reports.bp,
    clock_route.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire():
        """One global lock per request keeps every ledger move atomic."""
        db.lock.acquire()
        g._locked = True

    @app.teardown_request
    def _release(_exc=None):
        if getattr(g, "_locked", False):
            g._locked = False
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error("ERR_INVALID_REQUEST", "the requested path does not exist", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return response.error("ERR_INVALID_REQUEST",
                              "the method is not allowed for this path", 405)

    @app.errorhandler(400)
    def _bad_request(_exc):
        return response.error("ERR_INVALID_REQUEST", "the request body could not be parsed", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        return response.error("ERR_INVALID_REQUEST", "unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
