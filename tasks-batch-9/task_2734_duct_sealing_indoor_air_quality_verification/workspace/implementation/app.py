"""Duct Sealing & Indoor Air Quality Verification API.

Flask entry point.  Storage is in-memory only and starts EMPTY on every boot:
nothing is seeded, preloaded or hardcoded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import claims, clock, complaints, duct_systems, leakage_tests, programs, projects, reports, seal_jobs


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (clock, programs, projects, duct_systems, leakage_tests, seal_jobs,
                   reports, claims, complaints):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested route does not exist.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "The method is not allowed for this route.", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error_response("ERR_HTTP_%d" % (exc.code or 500),
                              exc.description or "HTTP error.", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
