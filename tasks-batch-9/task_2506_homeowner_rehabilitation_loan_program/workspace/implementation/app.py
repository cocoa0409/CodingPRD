"""Homeowner Rehabilitation Loan Program API.

Flask application factory and process entry point.  All state lives in the
in-memory dictionaries of db.py: nothing is persisted, nothing is seeded, and a
fresh process therefore always starts with every collection empty and the
logical clock reading exactly 2026-08-01T00:00:00Z.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import applicants, applications, change_orders, clock_routes, complaints
from routes import contractors, draw_requests, inspections, loans, program_years
from routes import solicitations, write_ups

BLUEPRINTS = (
    clock_routes.bp,
    program_years.bp,
    applicants.bp,
    applications.bp,
    inspections.bp,
    write_ups.bp,
    contractors.bp,
    solicitations.bp,
    loans.bp,
    draw_requests.bp,
    change_orders.bp,
    complaints.bp,
)

_LOCK = threading.RLock()


class SerializedMiddleware:
    """Serialize requests so every multi-hop cascade is atomic.

    The store is a plain dict graph; a request that writes several rows must not
    interleave with another request's reads.  Requests are cheap, so one global
    lock is both sufficient and simplest.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with _LOCK:
            return list(self.wsgi_app(environ, start_response))


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(error):
        status = error.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
            message = "The requested resource does not exist."
        elif status == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
            message = "The HTTP method is not allowed for this path."
        else:
            error_id = "ERR_INVALID_REQUEST"
            message = error.description or "The request could not be processed."
        return response.error_response(error_id, message, status)

    @app.errorhandler(Exception)
    def _handle_unexpected(error):  # pragma: no cover - defensive
        return response.error_response("ERR_INTERNAL", str(error) or "Internal error.", 500)

    app.wsgi_app = SerializedMiddleware(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
