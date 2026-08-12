"""Short Line Railroad Operations API — entry point.

In-memory only: the store starts empty on every boot; all entities are built
through the declared API surface. No seeding, no persistence.
"""

import os
import time

from flask import Flask

from envelope import error_response
from errors import ApiError, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_REQUEST

import routes_core
import routes_fleet
import routes_crew
import routes_movement
import routes_interchange
import routes_track
import routes_grants


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_fleet.bp)
    app.register_blueprint(routes_crew.bp)
    app.register_blueprint(routes_movement.bp)
    app.register_blueprint(routes_interchange.bp)
    app.register_blueprint(routes_track.bp)
    app.register_blueprint(routes_grants.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.http_status, err.error_id, err.message)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(404, ERR_RESOURCE_NOT_FOUND, "resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(405, ERR_INVALID_REQUEST, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(500, "ERR_INTERNAL", "internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Under per-test-server isolation the previous server on this port may have
    # been SIGKILLed only moments before this process starts; a transient
    # EADDRINUSE on bind would otherwise kill the boot and exhaust the
    # runner's readiness poll. Retry the bind for up to ~10s, then give up.
    for attempt in range(20):
        try:
            app.run(host="0.0.0.0", port=port)
            break
        except OSError:
            if attempt == 19:
                raise
            time.sleep(0.5)
