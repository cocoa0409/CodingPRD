"""Foreign Trade Letter of Credit API — entry point."""

import os
from flask import Flask
from errors import AppError
import response as resp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(AppError)
    def handle_app_error(e):
        return resp.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return resp.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return resp.error("ERR_INVALID_REQUEST", "Method not allowed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, AppError):
            return resp.error(e.error_id, e.message, e.http_status)
        return resp.error("ERR_INTERNAL", str(e), 500)

    from routes import register_routes
    register_routes(app)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
