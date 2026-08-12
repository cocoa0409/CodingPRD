"""Microschool Pod Management API — Flask entry point."""
import os

from flask import Flask

from core import ApiError, error_response, err
import routes_a
import routes_b
import routes_c
import routes_d


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_a.bp)
    app.register_blueprint(routes_b.bp)
    app.register_blueprint(routes_c.bp)
    app.register_blueprint(routes_d.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist"))

    @app.errorhandler(Exception)
    def handle_500(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error: %s" % e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
