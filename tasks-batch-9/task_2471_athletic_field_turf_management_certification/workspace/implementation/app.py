"""Athletic Field Turf Management and Certification service.

Storage is in process memory only and starts empty on every boot: nothing is
seeded, preloaded or hardcoded.  Every entity comes into existence through an
API call.
"""

import os

from flask import Flask

import response
from errors import ApiError
from routes import bp, clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error("ERR_NOT_FOUND", "No such resource.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return response.error("ERR_METHOD_NOT_ALLOWED",
                              "That method is not allowed on this path.", 405)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):  # pragma: no cover - handled above
            return response.error(exc.error_id, exc.message, exc.http_status)
        return response.error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
