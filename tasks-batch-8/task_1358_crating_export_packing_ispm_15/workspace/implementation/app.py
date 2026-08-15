"""Entry point: Flask app, error handlers, blueprint registration.

Contract (INSTRUCTION.md): reads $PORT (default 10000), binds 0.0.0.0,
runs in the foreground via `exec python3 app.py` from start.sh.
Store starts empty on every boot (in-memory only, no seeding).
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error as error_response
from routes import (customers, jobs, items, designs, wood, crates, hazmat,
                    docs, labor, containers, claims, clock)


def create_app():
    app = Flask(__name__)

    for bp in (customers.bp, jobs.bp, items.bp, designs.bp, wood.bp, crates.bp,
               hazmat.bp, docs.bp, labor.bp, containers.bp, claims.bp, clock.bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ERR_INVALID_REQUEST, "Unexpected error: %s" % err, 400)

    return app


app = create_app()

if __name__ == "__main__":
    import time

    port = int(os.environ.get("PORT", "10000"))
    # The per-test-server runner SIGKILLs the previous server on this port and
    # immediately spawns us; under concurrent sweeps the old socket can still
    # be closing when we first bind. Retry the bind instead of dying, so a
    # lingering predecessor cannot turn into a "could not be restarted" flake.
    for _ in range(60):
        try:
            app.run(host="0.0.0.0", port=port)
            break
        except OSError:
            time.sleep(0.5)
