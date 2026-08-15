"""Hospital Volunteer Services & Auxiliary API — Flask entry point."""
import os

from flask import Flask

from core import ApiError, error_response
import routes_core
import routes_org
import routes_ops
import routes_money


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))

    routes_core.register(app)
    routes_org.register(app)
    routes_ops.register(app)
    routes_money.register(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
