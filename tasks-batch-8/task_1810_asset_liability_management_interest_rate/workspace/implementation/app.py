"""Flask entry point: app factory, error envelope wiring, blueprint
registration. The store starts empty on every boot - nothing is seeded."""

import os

from flask import Flask

import routes
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(500)
    def _internal(_exc):
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
