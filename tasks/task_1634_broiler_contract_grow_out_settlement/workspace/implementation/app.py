"""Broiler Growout Settlement API — Flask entry point."""
import os

from flask import Flask

import db
from errors import ApiError
from response import error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Serialize all requests: the store is plain dicts, so one global lock
    # keeps every mutation (including cascades) atomic per request.
    @app.before_request
    def _acquire_lock():
        db.LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        db.LOCK.release()

    from routes import (
        clock,
        contracts,
        crews,
        flocks,
        groups,
        growers,
        houses,
        placements,
        schedules,
        settlements,
    )

    for module in (
        growers,
        contracts,
        houses,
        flocks,
        placements,
        schedules,
        groups,
        settlements,
        crews,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error("ERR_NOT_FOUND", "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error("ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
