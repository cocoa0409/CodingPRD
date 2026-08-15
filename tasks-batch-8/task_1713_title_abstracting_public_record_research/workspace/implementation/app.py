"""Title Abstracting & Public Record Research API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_VALIDATION
from response import error_body

from routes.clock import bp as clock_bp
from routes.orders import bp as orders_bp
from routes.assignments import bp as assignments_bp
from routes.documents import bp as documents_bp
from routes.checks import bp as checks_bp
from routes.reports import bp as reports_bp
from routes.curatives import bp as curatives_bp
from routes.retrievals import bp as retrievals_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        clock_bp,
        orders_bp,
        assignments_bp,
        documents_bp,
        checks_bp,
        reports_bp,
        curatives_bp,
        retrievals_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_body("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_body("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_body(ERR_VALIDATION, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", f"internal error: {exc}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
