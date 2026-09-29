"""School Boundary Redistricting API - Flask entry point.

Storage is purely in-memory and starts completely empty on every boot: the test
harness relaunches this process before every individual test, and no entity is
ever seeded, preloaded or hardcoded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
from routes.clock import bp as clock_bp
from routes.implementation import bp as implementation_bp
from routes.planning import bp as planning_bp
from routes.setup import bp as setup_bp

API_PREFIX = "/redistricting"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(setup_bp, url_prefix=API_PREFIX)
    app.register_blueprint(planning_bp, url_prefix=API_PREFIX)
    app.register_blueprint(implementation_bp, url_prefix=API_PREFIX)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        mapped = {
            400: "ERR_INVALID_REQUEST",
            404: "ERR_INVALID_REQUEST",
            405: "ERR_INVALID_REQUEST",
            415: "ERR_INVALID_REQUEST",
        }
        error_id = mapped.get(err.code, "ERR_INVALID_REQUEST")
        wrapped = ApiError(error_id, err.description if isinstance(err.description, str) else None)
        wrapped.http_status = err.code or 500
        return error_response(wrapped)

    return app


app = create_app()


if __name__ == "__main__":
    # threaded=True so a stale keep-alive socket left over from the previous
    # per-test reboot cannot block or truncate the next connection's response.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
