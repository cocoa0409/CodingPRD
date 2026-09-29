"""Solar Reroof Coordination API — Flask entrypoint.

Storage is in-memory only and always starts empty; nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import admin, deck, field, permits, projects, reference, sourcing, windows


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        reference,
        projects,
        field,
        deck,
        permits,
        windows,
        sourcing,
        admin,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        code = exc.code or 500
        if code == 404:
            error_id = "ERR_NOT_FOUND"
        elif code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif code >= 500:
            error_id = "ERR_INTERNAL"
        else:
            error_id = "ERR_INVALID_REQUEST"
        return error_response(error_id, exc.description or exc.name, code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
