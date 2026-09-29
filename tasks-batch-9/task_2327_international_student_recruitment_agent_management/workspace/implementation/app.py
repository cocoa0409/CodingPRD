"""International Student Recruitment Agent Management API.

In-memory only: every process starts with an empty store and a fixed logical clock.
"""

import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from errors import ApiError
from response import error
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        return error(errors.ERR_INVALID_REQUEST, exc.description or exc.name,
                     exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc()
        return error(errors.ERR_INVALID_REQUEST, "Unexpected server error: %s" % exc, 500)

    @app.route("/health", methods=["GET"])
    def health():
        return {"status": "ok"}, 200

    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
