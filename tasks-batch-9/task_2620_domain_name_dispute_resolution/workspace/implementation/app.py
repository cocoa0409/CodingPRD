"""Entry point: application factory, error handlers and route registration."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.registry import bp as registry_bp
from routes.cases import bp as cases_bp
from routes.panel import bp as panel_bp
from routes.decisions import bp as decisions_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(registry_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(panel_bp)
    app.register_blueprint(decisions_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.fail(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.fail("ERR_RESOURCE_NOT_FOUND", "No such route.", 404)
        if exc.code == 405:
            return response.fail("ERR_RESOURCE_NOT_FOUND",
                                 "Method not allowed on this route.", 404)
        if exc.code and 400 <= exc.code < 500:
            return response.fail("ERR_INVALID_REQUEST", exc.description or "Bad request.", 400)
        return response.fail("ERR_INTERNAL", exc.description or "Server error.",
                             exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - safety net
        return response.fail("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
