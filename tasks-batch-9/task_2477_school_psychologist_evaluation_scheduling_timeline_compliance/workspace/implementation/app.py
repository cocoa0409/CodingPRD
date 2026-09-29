"""School Psych Evaluation Timeline API.

A single-process Flask service holding every record in memory. The store is
empty on every boot: nothing is seeded, preloaded or read from disk.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import respond_error
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return respond_error(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        if error.code == 404:
            return respond_error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if error.code == 405:
            return respond_error("ERR_METHOD_NOT_ALLOWED",
                                 "That method is not allowed on this resource.", 405)
        if error.code in (400, 415):
            return respond_error("ERR_INVALID_REQUEST",
                                 error.description or "The request could not be parsed.", 422)
        return respond_error("ERR_INTERNAL", error.description or "Internal error.",
                             error.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - defensive
        return respond_error("ERR_INTERNAL", "Internal server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
