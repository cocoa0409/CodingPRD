"""Adult Education HSE Testing API -- in-memory Flask service.

Storage is a set of plain Python dicts held in this process only. Nothing is
seeded, preloaded or persisted: every record is created by a client call.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import error_response
from errors import ApiError, ERROR_STATUS

import routes_students
import routes_centers
import routes_instruction
import routes_exams
import routes_funding


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_students.bp)
    app.register_blueprint(routes_centers.bp)
    app.register_blueprint(routes_instruction.bp)
    app.register_blueprint(routes_exams.bp)
    app.register_blueprint(routes_funding.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed for this path.", 405)
        if exc.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST",
                                  "The request body is not valid.", 400)
        return error_response("ERR_INTERNAL",
                              exc.description or "Unexpected error.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
