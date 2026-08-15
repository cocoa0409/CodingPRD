"""Privacy Program & Data Mapping API — Flask entry point."""
import os

from flask import Flask

import response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    from routes import register_all
    register_all(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err)

    @app.errorhandler(404)
    def handle_not_found(_):
        return response.error(ApiError("ERR_NOT_FOUND", "resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return response.error(err)
        wrapped = ApiError("ERR_INVALID_REQUEST", str(err))
        wrapped.http_status = 500
        return response.error(wrapped)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
