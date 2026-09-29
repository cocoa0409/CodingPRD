"""CNC Swiss Screw Machine Shop API — entry point.

The in-memory store starts completely empty on every boot: no entity is ever
seeded, preloaded or hardcoded. Tests build every precondition through the
declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
import routes_commerce
import routes_masters
import routes_production


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_masters.bp)
    app.register_blueprint(routes_commerce.bp)
    app.register_blueprint(routes_production.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return respond_error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return respond_error("ERR_INVALID_REQUEST", "Method not allowed for this path.", 400)
        if exc.code and 400 <= exc.code < 500:
            return respond_error("ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400)
        return respond_error("ERR_INTERNAL", exc.description or "Internal server error.", 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return respond_error("ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


application = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
