"""New Teacher Induction & Mentorship Program API.

Storage is in-memory only and always starts empty: nothing is seeded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_attainments
import routes_config
import routes_contact_logs
import routes_matching
import routes_mentors
import routes_novices
import routes_observations
import routes_packets
import routes_seminars
import routes_stipends
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (routes_config, routes_mentors, routes_novices, routes_matching,
                   routes_contact_logs, routes_observations, routes_seminars,
                   routes_attainments, routes_stipends, routes_packets):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND", "Resource not found.", 404))
        if err.code == 405:
            return error_response(ApiError("ERR_NOT_FOUND", "Method not allowed.", 404))
        if err.code == 400:
            return error_response(ApiError("ERR_INVALID_REQUEST", "Malformed request."))
        return error_response(ApiError("ERR_INTERNAL", str(err), err.code or 500))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", "Internal server error.", 500))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
