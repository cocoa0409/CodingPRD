"""Tortilla & Masa Production API — Flask entry point."""
import os

from flask import Flask

from db import store
from errors import ApiError
from response import err_response, error_body
from flask import jsonify

from routes.clock import bp as clock_bp
from routes.mill import bp as mill_bp
from routes.products import bp as products_bp
from routes.lines import bp as lines_bp
from routes.runs import bp as runs_bp
from routes.packs import bp as packs_bp
from routes.sales import bp as sales_bp
from routes.logistics import bp as logistics_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _reset_touched():
        store.touched.clear()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return err_response(e)

    @app.errorhandler(404)
    def _not_found(e):
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, ApiError):
            return err_response(e)
        return jsonify(error_body("ERR_INTERNAL", str(e))), 500

    for bp in (clock_bp, mill_bp, products_bp, lines_bp, runs_bp, packs_bp,
               sales_bp, logistics_bp):
        app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
