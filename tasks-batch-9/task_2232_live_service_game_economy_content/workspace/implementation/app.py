"""Live-service game economy and content API -- Flask application factory.

Storage is an in-memory dict store that starts completely empty on every boot;
nothing is seeded, preloaded or persisted to disk.
"""
import os

from flask import Flask, g

import db
from errors import ApiError
from response import error_response
from routes import (
    capacity,
    episodes,
    monitoring,
    offers,
    players,
    purchases,
    refunds,
    seasons,
    tuning,
)

BLUEPRINTS = (
    seasons.bp,
    episodes.bp,
    capacity.bp,
    players.bp,
    offers.bp,
    purchases.bp,
    refunds.bp,
    tuning.bp,
    monitoring.bp,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin():
        g.touched_ids = set()
        db.lock.acquire()

    @app.teardown_request
    def _end(_exc=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_NOT_FOUND", "The requested route does not exist.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this route.", 405
        )

    @app.errorhandler(400)
    def _bad_request(_exc):
        return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
