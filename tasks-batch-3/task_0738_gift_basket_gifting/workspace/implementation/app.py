"""Flask entry point."""
import os
import traceback

from flask import Flask

from errors import APIError, HTTP_STATUS, ERR_BAD_REQUEST
from response import error as error_response
from routes import bp as api_bp


def create_app():
    app = Flask(__name__)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_ROUTE_NOT_FOUND", 404, "route not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", 500, str(e))

    app.register_blueprint(api_bp)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
