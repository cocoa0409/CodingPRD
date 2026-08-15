"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import err
import routes


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return err("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err(e.error_id, e.http_status, e.message)
        return err("ERR_INVALID_REQUEST", 400, str(e))

    routes.register(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
