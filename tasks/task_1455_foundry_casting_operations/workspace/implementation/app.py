"""Entry point: Flask app, error handlers, route registration.

The store is process-local and starts EMPTY (db.py module state); no entity
is seeded at startup. The logical clock defaults to 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import register_all


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INVALID_REQUEST", str(err), 400)

    register_all(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
