"""Flask entry point: app factory, error handlers, blueprint registration."""
import os

from flask import Flask

import routes_compete  # noqa: F401  (registers routes on the shared blueprint)
import routes_core  # noqa: F401
from bp import bp
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", 500, str(err))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
