"""Immigration Legal Services Program API.

Flask application factory and error handling. All state lives in process-local
dictionaries in store.py; the process starts with an empty store on every boot.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import authority, calendar, casework, core, decisions, intake, matters
from routes import reports, staffing

BLUEPRINTS = (
    core.bp,
    authority.bp,
    intake.bp,
    matters.bp,
    staffing.bp,
    casework.bp,
    calendar.bp,
    decisions.bp,
    reports.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "The requested route does not exist.",
                                  404)
        if exc.code == 405:
            return response.error("ERR_NOT_FOUND",
                                  "The method is not allowed for this route.", 404)
        if exc.code in (400, 415):
            return response.error("ERR_VALIDATION",
                                  "The request payload could not be parsed.", 422)
        return response.error("ERR_INVARIANT_VIOLATION",
                              exc.description or "Unexpected error.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INVARIANT_VIOLATION", str(exc) or "Unexpected error.",
                              500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
