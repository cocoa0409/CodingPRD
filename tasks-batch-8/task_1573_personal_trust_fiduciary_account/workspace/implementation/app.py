"""Entry point: Flask app, error handlers, route registration.

Storage is in-memory only (module-level dicts in db.py); every fresh process
boots with an empty store — no seeding, no files, no caches.
"""

import os

from flask import Flask

from errors import ApiError, ERR_RESOURCE_NOT_FOUND, ERR_VALIDATION
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response(ERR_RESOURCE_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response(ERR_VALIDATION, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", "Internal error: %s" % e, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
