"""Flask application factory for the Chargemaster Maintenance API."""

import os

from flask import Flask

from envelope import error_response
from errors import ApiError

BLUEPRINT_MODULES = (
    "routes_clock",
    "routes_facilities",
    "routes_pricing",
    "routes_items",
    "routes_requests",
    "routes_code_update",
    "routes_capture",
    "routes_contracts",
    "routes_transparency",
)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    for name in BLUEPRINT_MODULES:
        module = __import__(name)
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return error_response(ApiError("ERR_VALIDATION", "Unknown route."))

    @app.errorhandler(405)
    def _bad_method(_err):
        return error_response(ApiError("ERR_VALIDATION", "Method not allowed."))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unhandled error")
        return error_response(
            ApiError("ERR_VALIDATION", "Unhandled server error: %s" % err)
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
    )
