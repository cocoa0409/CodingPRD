"""Timberland Investment Management API.

A single-process Flask application whose entire state lives in memory: the store
starts empty on every boot and nothing is ever seeded, so each fresh launch of
start.sh presents a clean system.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import routes
from errors import DEFAULT_MESSAGES, ApiError


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.error_response(error.error_id, error.message,
                                       error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        # Unroutable paths and unsupported methods still answer in the envelope.
        return response.error_response(
            "ERR_INVALID_REQUEST",
            error.description or DEFAULT_MESSAGES["ERR_INVALID_REQUEST"],
            error.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return response.error_response("ERR_INVALID_REQUEST", str(error), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
