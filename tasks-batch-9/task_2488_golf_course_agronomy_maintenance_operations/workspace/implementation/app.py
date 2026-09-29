"""Golf Course Agronomy & Maintenance Operations API.

Storage is in-memory only and every collection starts empty on every boot.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    from routes.applications import bp as applications_bp
    from routes.courses import bp as courses_bp
    from routes.fleet import bp as fleet_bp
    from routes.irrigation import bp as irrigation_bp
    from routes.plans import bp as plans_bp
    from routes.windows import bp as windows_bp

    for blueprint in (courses_bp, plans_bp, applications_bp, irrigation_bp,
                      windows_bp, fleet_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        code = error.code or 500
        if code == 400:
            return error_response(
                "ERR_INVALID_REQUEST",
                "The request payload is malformed or violates a field constraint.", 400)
        if code == 404:
            return error_response("ERR_NOT_FOUND", "No such endpoint.", 404)
        if code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "That method is not allowed on this endpoint.", 405)
        return error_response("ERR_REQUEST_FAILED",
                              error.description or "The request could not be served.",
                              code)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return error_response(error.error_id, error.message, error.http_status)
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
