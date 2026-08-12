"""Flask entry point: error handlers, route registration, server boot."""
import os
import traceback

from flask import Flask

from errors import ApiError
from response import err_response
import routes


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return err_response(error)

    @app.errorhandler(404)
    def handle_404(error):
        return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(error):
        return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        traceback.print_exc()
        return err_response(ApiError("ERR_INTERNAL", 500, str(error)))

    routes.register_all(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
