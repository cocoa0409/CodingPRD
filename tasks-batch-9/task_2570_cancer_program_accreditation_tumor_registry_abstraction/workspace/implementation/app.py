"""Cancer Program Accreditation & Tumor Registry Abstraction API.

Flask application factory plus the WSGI entry point.  All state lives in
process memory (see db.py); nothing is seeded at boot.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError, _default_message
from response import error_response
from routes import (abstractions, abstractors, audits, cases, casefinding,
                    clock, conferences, deficiencies, measures, programs,
                    submissions)

BLUEPRINTS = (
    programs.bp,
    abstractors.bp,
    casefinding.bp,
    cases.bp,
    abstractions.bp,
    audits.bp,
    conferences.bp,
    submissions.bp,
    deficiencies.bp,
    measures.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.before_request
    def _init_request_scope():
        g._dirty = {}
        g._forced = set()
        g._fresh_ids = set()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _handle_405(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "Method not allowed for this resource.", 405)

    @app.errorhandler(HTTPException)
    def _handle_http(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  _default_message("ERR_INVALID_REQUEST"), 400)
        return error_response("ERR_HTTP_%s" % exc.code,
                              exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INTERNAL",
                              "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True,
            use_reloader=False)
