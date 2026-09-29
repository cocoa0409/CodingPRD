"""Food Broker Authorization & Slotting API.

A single Flask process holding all state in memory.  Nothing is persisted and
nothing is seeded: every boot starts from an empty store.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return response.error(
                "ERR_METHOD_NOT_ALLOWED",
                "The requested method is not allowed for this resource.",
                405,
            )
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return response.error(
            "ERR_HTTP_%d" % (exc.code or 500),
            exc.description or "Request failed.",
            exc.code or 500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
