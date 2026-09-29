"""Hazardous Waste Treatment Facility Operations API.

A single Flask process holding every row in memory. The store is empty at boot:
nothing is ever seeded, so a fresh process always starts from zero rows and the
logical clock's initial instant.
"""

import os

from flask import Flask, request

from errors import ApiError
from response import error_response
from routes import register_all


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    register_all(app)

    @app.before_request
    def drain_request_body():
        # Read the whole request body before any handler can answer. A request
        # refused on identity or role is answered without the body ever being
        # parsed, and closing a socket that still holds unread bytes makes the
        # kernel send RST instead of FIN — which reaches the caller as a reset
        # connection rather than the refusal it asked for. Cached, so the
        # handlers still read the same body afterwards.
        request.get_data(cache=True)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Request body or query parameters are invalid", 400)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Addressed resource does not exist", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response("ERR_ROLE_NOT_PERMITTED",
                              "Role is not permitted to perform this operation", 405)

    @app.errorhandler(500)
    def handle_internal(_exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Request body or query parameters are invalid", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
