"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import err
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")

    @app.errorhandler(405)
    def handle_405(e):
        return err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")

    @app.errorhandler(400)
    def handle_400(e):
        return err("ERR_VALIDATION", 400, "Malformed request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
