"""Pension Risk Transfer API — Flask application factory and entry point.

Storage is entirely in-memory and starts empty on every boot; nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import buyout, complaints, participants, plans, windows


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(plans.bp)
    app.register_blueprint(participants.bp)
    app.register_blueprint(windows.bp)
    app.register_blueprint(buyout.bp)
    app.register_blueprint(complaints.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        status = error.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", "The requested route does not exist.", 404)
        if status == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this route.", 405
            )
        if status in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST", "The request body is malformed or missing.", 422
            )
        return error_response("ERR_INTERNAL", error.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "An unexpected server error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
