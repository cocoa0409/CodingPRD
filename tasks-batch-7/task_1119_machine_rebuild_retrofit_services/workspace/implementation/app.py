"""Entry point: Flask app, error handlers, blueprint registration.

The store starts empty on every boot — no seeding anywhere. Every entity any
test needs is constructed through the declared API surface.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_response


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    from routes import (
        acceptance,
        assessments,
        claims,
        clock,
        customers,
        machines,
        offers,
        parts,
        projects,
        rejobs,
        stages,
        training,
        windows,
    )

    for module in (
        customers,
        machines,
        assessments,
        projects,
        parts,
        rejobs,
        acceptance,
        training,
        windows,
        stages,
        claims,
        offers,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", f"unexpected error: {err}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
