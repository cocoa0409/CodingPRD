"""Airport Rental Car CFC API — Flask entry point.

The in-memory store starts completely empty on every boot: no entity is seeded,
preloaded or hardcoded. Tests build all state through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response as resp
from errors import ApiError
from store import LOCK

import routes_facility
import routes_space
import routes_report
import routes_finance


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_facility.bp)
    app.register_blueprint(routes_space.bp)
    app.register_blueprint(routes_report.bp)
    app.register_blueprint(routes_finance.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return resp.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            return resp.error("ERR_INVALID_REQUEST", "Unknown resource path.", 404)
        if status == 405:
            return resp.error("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if status == 400:
            return resp.error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return resp.error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                          status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return resp.error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    # Every request runs under one process-wide lock so multi-step cascades are
    # atomic with respect to concurrent callers.
    inner_wsgi = app.wsgi_app

    def locked_wsgi(environ, start_response):
        with LOCK:
            return inner_wsgi(environ, start_response)

    app.wsgi_app = locked_wsgi
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
