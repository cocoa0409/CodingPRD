"""Media Archive Operations API — Flask entry point.

Mounts all /archive blueprints and renders the standard error envelope for
API errors as well as generic 404/405/500 failures. State is in-memory only;
every fresh process starts with an empty store and the logical clock at
2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

import routes_clock
import routes_disposal
import routes_finance
import routes_ingest
import routes_lab
import routes_retrieval
import routes_rights
import routes_staff
from envelope import err_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for mod in (
        routes_clock,
        routes_staff,
        routes_ingest,
        routes_rights,
        routes_disposal,
        routes_retrieval,
        routes_finance,
        routes_lab,
    ):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return err_response(ApiError(404, "ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return err_response(ApiError(405, "ERR_METHOD_NOT_ALLOWED", "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err_response(e)
        return err_response(ApiError(500, "ERR_INTERNAL", "Internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
