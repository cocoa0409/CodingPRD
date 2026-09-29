"""Vehicle Service Information Access API -- Flask application entry point.

State lives entirely in process memory (see store.py) and is empty on every
boot, so the harness can relaunch this process before each test.
"""

import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return error_response(
            "ERR_INVALID_REQUEST", error.description or "The request could not be handled.", error.code
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "The request could not be handled.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
