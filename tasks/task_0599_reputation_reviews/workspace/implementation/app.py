"""Online Reputation Management API -- entry point.

Storage is in-memory only; the store starts empty on every boot and no entity
is ever seeded, preloaded or hardcoded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError, err
from routes import (businesses, campaigns, escalations, listings, locations,
                    misc, requests, responses, reviews, surveys, widgets)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (businesses, locations, listings, campaigns, requests,
                   reviews, responses, escalations, surveys, widgets, misc):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(err("ERR_LOCATION_NOT_FOUND", "Unknown route."))
        if exc.code == 405:
            return error_response(err("ERR_INVALID_REQUEST", "Method not allowed."))
        if exc.code in (400, 415):
            return error_response(err("ERR_INVALID_REQUEST"))
        return error_response(err("ERR_INVALID_REQUEST", exc.description or "Request failed."))

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover -- defensive
        app.logger.exception("unhandled error")
        return error_response(err("ERR_INVALID_REQUEST", "Internal error: %s" % exc))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
