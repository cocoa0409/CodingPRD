import os
from flask import Flask

from errors import ApiError, ERR_RESOURCE_NOT_FOUND
from response import error_envelope
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_envelope(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_envelope(ERR_RESOURCE_NOT_FOUND[0],
                              "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_envelope(ERR_RESOURCE_NOT_FOUND[0],
                              "Method not allowed", 405)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
