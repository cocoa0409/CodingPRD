"""Youth Orchestra Audition and Seating Service — Flask application factory.

Storage is in-memory only: every process starts with completely empty tables and
no seeded rows whatsoever.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import BLUEPRINTS
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return error("ERR_METHOD_NOT_ALLOWED",
                     "That method is not allowed on this route.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", "The request body is malformed.", 400)
        return error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                     exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
