"""Graduate Assistantship Stipend Administration API.

Flask application factory and process entry point.  Storage is in-memory only
and starts completely empty on every boot: nothing is seeded or preloaded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes import (allocations, appointments, clock, disbursements, funding,
                    renewals, students, tax, terms)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (terms, students, funding, appointments, allocations,
                   disbursements, renewals, tax, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "The requested resource does not exist", 404)
        if exc.code == 405:
            return error("ERR_METHOD_NOT_ALLOWED",
                         "The method is not allowed for this resource", 405)
        if exc.code in (400, 415):
            return error("ERR_INVALID_REQUEST", exc.description or "Malformed request", 422)
        return error("ERR_INTERNAL", exc.description or "Unexpected error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error("ERR_INTERNAL", "Unexpected server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
