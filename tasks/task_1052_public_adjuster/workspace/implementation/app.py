"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

from common import ApiError, error_response
from routes import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp, url_prefix="/v1")

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed")

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_VALIDATION", "Malformed request")

    @app.errorhandler(Exception)
    def handle_uncaught(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message)
        return error_response("ERR_VALIDATION", "Unexpected error: %s" % err)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
