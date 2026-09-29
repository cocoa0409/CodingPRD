"""Application factory and process entrypoint.

State lives entirely in module-level Python dicts (see db.py); nothing is
persisted and nothing is seeded, so a fresh process always starts empty with
the logical clock at its epoch.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import clock
import db
import response
import routes
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    clock.reset()
    db.reset_all()

    routes.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_out(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return response.error_out(
            "ERR_NOT_FOUND", "The requested route does not exist.", 404
        )

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error_out(
            "ERR_NOT_FOUND", "The method is not allowed for this route.", 405
        )

    @app.errorhandler(400)
    def handle_400(exc):
        return response.error_out(
            "ERR_INVALID_REQUEST", "The request is malformed.", 400
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        error_id = "ERR_INVALID_REQUEST" if exc.code and exc.code < 500 else "ERR_INTERNAL"
        return response.error_out(error_id, exc.description, exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error_out("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
