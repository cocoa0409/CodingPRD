"""Entry point: Flask app assembly, error handlers, route registration."""

import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    from routes import (
        audit,
        clock,
        expenses,
        funders,
        grants,
        match,
        modifications,
        renewals,
        reports,
    )

    for module in (
        funders,
        grants,
        expenses,
        reports,
        match,
        modifications,
        audit,
        renewals,
        clock,
    ):
        module.register(app)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
