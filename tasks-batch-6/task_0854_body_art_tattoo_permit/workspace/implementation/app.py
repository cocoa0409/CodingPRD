"""Body-Art & Tattoo Establishment Permit API — entry point.

The in-memory store starts EMPTY on every boot; nothing is seeded here.
"""

import os

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

import store
from envelope import error_response
from errors import ApiError
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    # Immediate consistency: every request is applied atomically against the
    # in-memory store, so concurrent writers observe a serial order.
    @app.before_request
    def acquire_store_lock():
        store.LOCK.acquire()
        g.holds_store_lock = True

    @app.teardown_request
    def release_store_lock(_exc=None):
        if g.pop("holds_store_lock", False):
            store.LOCK.release()

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response(
            "ERR_VALIDATION", "No route matches the requested path.", 404
        )

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response(
            "ERR_VALIDATION", "Method not allowed for this path.", 405
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return error_response(
                "ERR_VALIDATION", exc.description or exc.name, exc.code or 400
            )
        app.logger.exception("unhandled error on %s %s", request.method, request.path)
        return error_response("ERR_VALIDATION", str(exc), 400)

    @app.after_request
    def close_connection(response):
        # the per-test-server harness relaunches the process between tests;
        # keep-alive sockets otherwise surface as RemoteDisconnected flakiness.
        response.headers["Connection"] = "close"
        return response

    return app


app = create_app()


def registered_route_count():
    seen = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        for method in rule.methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            seen.add((method, str(rule)))
    return len(seen)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
