"""Entry point: Flask app assembly, error handlers, route registration."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask

import errors as E
from errors import ApiError
from response import error as error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (ops, families, clients, coaches, intakes, plans, goals,
                        packages, sessions, checkins, snapshots, coordination,
                        workshops, supervision)
    for module in (ops, families, clients, coaches, intakes, plans, goals,
                   packages, sessions, checkins, snapshots, coordination,
                   workshops, supervision):
        app.register_blueprint(module.bp, url_prefix="/api")

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError(E.ERR_NOT_FOUND, "Resource not found", 404))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError(E.ERR_NOT_FOUND, "Resource not found", 404))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError(E.ERR_VALIDATION, str(err), 400))

    return app


app = create_app()

if __name__ == "__main__":
    import errno
    import time

    port = int(os.environ.get("PORT", "10000"))
    # The per-test-server harness kill -9's the previous listener and respawns
    # immediately; under parallel load the old socket can outlive the kill by a
    # few hundred ms. Retry the bind instead of dying, so the runner's restart
    # poll window is spent waiting for a server that will actually come up.
    for attempt in range(50):
        try:
            app.run(host="0.0.0.0", port=port)
            break
        except OSError as err:
            if err.errno == errno.EADDRINUSE and attempt < 49:
                time.sleep(0.2)
                continue
            raise
