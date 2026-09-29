"""Player Tracking Data Ops API — application entry point.

All state lives in the in-memory store of ``db.py``; nothing is persisted and
nothing is seeded.  A fresh process therefore starts with every collection empty
and the logical clock at its fixed startup default, which is exactly what the
per-test-server harness expects.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from db import request_lock
from errors import ApiError
from response import error_response
from routes import clock as clock_routes
from routes import clubs as club_routes
from routes import feeds as feed_routes
from routes import games as game_routes
from routes import rights as rights_routes
from routes import tags as tag_routes
from routes import venues as venue_routes


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (venue_routes, club_routes, game_routes, tag_routes,
                   rights_routes, feed_routes, clock_routes):
        app.register_blueprint(module.bp)

    @app.before_request
    def _acquire_lock():
        # Every request is serialised: the census, ledger and cascade
        # invariants of PRD §2.11 must hold at every observable instant.
        request_lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            request_lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        return error_response(
            "ERR_INVALID_REQUEST",
            exc.description or "The request could not be processed.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
