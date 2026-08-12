import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes_core import bp as core_bp
from routes_ops import bp as ops_bp
from routes_ops2 import bp as ops2_bp
from routes_supply import bp as supply_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(core_bp)
    app.register_blueprint(ops_bp)
    app.register_blueprint(ops2_bp)
    app.register_blueprint(supply_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_exception(e):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
