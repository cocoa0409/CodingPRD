import os

from flask import Flask

from errors import ApiError
from store import STORE
from util import err_response, ok

from routes.clock import bp as clock_bp
from routes.products_lines import bp as products_lines_bp
from routes.runs import bp as runs_bp
from routes.checks import bp as checks_bp
from routes.changeovers import bp as changeovers_bp
from routes.oils import bp as oils_bp
from routes.shipments import bp as shipments_bp
from routes.promos import bp as promos_bp
from routes.coman import bp as coman_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (clock_bp, products_lines_bp, runs_bp, checks_bp, changeovers_bp,
               oils_bp, shipments_bp, promos_bp, coman_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_response(STORE, e)

    @app.errorhandler(404)
    def handle_404(e):
        return err_response(STORE, ApiError("ERR_NOT_FOUND", 404, "resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return err_response(STORE, ApiError("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        app.logger.exception("unexpected error")
        return err_response(STORE, ApiError("ERR_INTERNAL", 500, str(e)))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
