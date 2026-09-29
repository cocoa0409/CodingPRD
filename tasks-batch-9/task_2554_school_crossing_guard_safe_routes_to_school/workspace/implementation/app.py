"""School Crossing Guard & Safe Routes to School API.

A single Flask process holding all state in memory.  Nothing is seeded: every
school, intersection, guard, post, route, complaint, grant program and project
is created through the declared endpoints, so a fresh boot is always an empty
system.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (absences, clock, complaints, grants, guards, intersections,
                    posts, schools, studies, walking_routes)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    for module in (schools, intersections, studies, guards, posts, absences,
                   walking_routes, complaints, grants, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
            message = "No resource is routed at this path."
        elif status == 405:
            error_id = "ERR_INVALID_REQUEST"
            message = "This method is not allowed on this path."
        else:
            error_id = "ERR_INVALID_REQUEST"
            message = exc.description or "The request could not be processed."
        return error_response(error_id, message, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", str(exc) or "Unhandled error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
