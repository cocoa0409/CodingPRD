"""Camp Accreditation & Health Compliance API.

Storage is in-memory only and every collection starts empty on every boot:
no entity data is ever seeded, preloaded or hardcoded.
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
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.failure(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        status = error.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
            message = "The requested resource does not exist."
        elif status == 405:
            error_id = "ERR_INVALID_REQUEST"
            message = "The HTTP method is not allowed for this path."
        elif status == 400:
            error_id = "ERR_INVALID_REQUEST"
            message = "The request could not be parsed."
        else:
            error_id = "ERR_INVALID_REQUEST"
            message = error.description or "Request failed."
        return response.failure(error_id, message, status)

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - defensive
        return response.failure("ERR_INVALID_REQUEST", str(error), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
