"""Furniture Upholstery Mill API — Flask entry point."""
import os

from flask import Flask

from mill.common import ApiError, error_response, ok
from mill.routes_catalog import bp as catalog_bp
from mill.routes_cells import bp as cells_bp
from mill.routes_finish import bp as finish_bp
from mill.routes_materials import bp as materials_bp
from mill.routes_orders import bp as orders_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (catalog_bp, orders_bp, materials_bp, cells_bp, finish_bp):
        app.register_blueprint(bp)

    @app.route("/", methods=["GET"])
    def root():
        return ok({"status": "ok"})

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ApiError("ERR_INVALID_REQUEST", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ApiError("ERR_INVALID_REQUEST", 405, "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(ApiError("ERR_INVALID_REQUEST", 500, str(e)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
