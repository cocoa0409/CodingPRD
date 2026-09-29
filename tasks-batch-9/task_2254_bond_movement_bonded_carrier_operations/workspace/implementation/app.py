"""In-Bond Movement & Bonded Carrier Operations API.

A single Flask process holding all state in memory.  Boot is side-effect free:
the store starts completely empty on every launch.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import (amendments, claims, clock, holds, movements, petitions,
                    registry, reports, seals, sweeps)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (registry, movements, seals, holds, amendments, reports,
                   claims, petitions, sweeps, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(_err):
        return error_response(ApiError("ERR_RESOURCE_NOT_FOUND"))

    @app.errorhandler(405)
    def _handle_405(_err):
        err = ApiError("ERR_RESOURCE_NOT_FOUND", "method not allowed")
        err.http_status = 405
        return error_response(err)

    @app.errorhandler(400)
    def _handle_400(_err):
        return error_response(ApiError("ERR_INVALID_REQUEST"))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        wrapped = ApiError("ERR_INVALID_REQUEST", str(err))
        wrapped.http_status = 500
        return error_response(wrapped)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, use_reloader=False)
