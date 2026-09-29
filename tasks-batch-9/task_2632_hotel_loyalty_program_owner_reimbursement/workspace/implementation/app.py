"""Hotel Loyalty Owner Reimbursement API.

A single-process Flask application whose entire state lives in memory: every
entity is created by a caller through the declared endpoints, nothing is seeded
at start-up, and a fresh process therefore always begins with an empty
programme (bar the singleton programme fund, which the PRD says exists from
server start).
"""

import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError
from routes import complaints, hotels, members, points, redemptions, stays
from services import derive


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(hotels.bp)
    app.register_blueprint(members.bp)
    app.register_blueprint(stays.bp)
    app.register_blueprint(redemptions.bp)
    app.register_blueprint(points.bp)
    app.register_blueprint(complaints.bp)

    @app.before_request
    def _open_request():
        db.begin_request()
        derive.ensure_fund()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(exc):
        return response.error_response("ERR_INVALID_REQUEST",
                                       "The request payload is malformed.", 400)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error_response("ERR_NOT_FOUND",
                                       "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return response.error_response("ERR_METHOD_NOT_ALLOWED",
                                       "The HTTP method is not supported for this path.",
                                       405)

    @app.errorhandler(Exception)
    def _internal(exc):
        if isinstance(exc, ApiError):
            return response.error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            status = exc.code or 500
            if status == 404:
                return response.error_response(
                    "ERR_NOT_FOUND", "The requested resource does not exist.", 404)
            if status == 405:
                return response.error_response(
                    "ERR_METHOD_NOT_ALLOWED",
                    "The HTTP method is not supported for this path.", 405)
            if status < 500:
                return response.error_response(
                    "ERR_INVALID_REQUEST", "The request payload is malformed.", status)
        traceback.print_exc()
        return response.error_response("ERR_INTERNAL",
                                       "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
