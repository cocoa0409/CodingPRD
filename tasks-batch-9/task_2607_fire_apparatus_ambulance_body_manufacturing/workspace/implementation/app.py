"""Fire Apparatus & Ambulance Body Manufacturing API.

A single Flask process with in-memory dictionary storage. The store is empty on
every boot — nothing is seeded, preloaded or read from disk — so the harness can
kill and relaunch this process before every individual test and still see a
clean plant.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes import certs, changes, programs, specs, supply, units


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(programs.bp)
    app.register_blueprint(specs.bp)
    app.register_blueprint(units.bp)
    app.register_blueprint(supply.bp)
    app.register_blueprint(changes.bp)
    app.register_blueprint(certs.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        return error(
            "ERR_INVALID_REQUEST",
            exc.description or "The request could not be served.",
            status,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
