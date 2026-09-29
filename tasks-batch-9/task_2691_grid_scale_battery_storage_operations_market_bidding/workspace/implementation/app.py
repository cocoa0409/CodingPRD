"""Grid-Scale Battery Storage Operations API.

Entry point: registers every blueprint and installs the error handlers that
render the standard envelope of PRD 2.2.  The in-memory store starts EMPTY on
every boot — nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from errors import ApiError
from routes import (assets, bids, captests, claims, dispatches, obligations,
                    reservations, safety, telemetry)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:  # Flask >= 2.2 keeps JSON settings on app.json
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for module in (assets, reservations, bids, dispatches, telemetry, safety,
                   obligations, captests, claims):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error(errors.ERR_INVALID_REQUEST,
                                  "The requested resource does not exist.", 404)
        if exc.code == 405:
            return response.error(errors.ERR_INVALID_REQUEST,
                                  "The method is not allowed for this path.", 405)
        if exc.code and exc.code < 500:
            return response.error(errors.ERR_INVALID_REQUEST,
                                  exc.description or "Malformed request.",
                                  exc.code)
        return response.error("ERR_INTERNAL", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error("ERR_INTERNAL", "Internal server error: %s" % exc,
                              500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
