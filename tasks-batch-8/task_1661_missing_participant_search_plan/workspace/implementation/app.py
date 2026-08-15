"""Missing Participant Search & Plan Termination API -- Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_body

from routes.clock import bp as clock_bp
from routes.cases import bp as cases_bp
from routes.participants import bp as participants_bp
from routes.search import bp as search_bp
from routes.notices import bp as notices_bp
from routes.blackouts import bp as blackouts_bp
from routes.elections import bp as elections_bp
from routes.payouts import bp as payouts_bp
from routes.pbgc import bp as pbgc_bp
from routes.forfeitures import bp as forfeitures_bp
from routes.dlrs import bp as dlrs_bp
from routes.logs import bp as logs_bp
from routes.expenses import bp as expenses_bp


def create_app():
    app = Flask(__name__)
    try:
        app.json.sort_keys = False
    except AttributeError:
        app.config["JSON_SORT_KEYS"] = False

    for bp in (
        clock_bp,
        cases_bp,
        participants_bp,
        search_bp,
        notices_bp,
        blackouts_bp,
        elections_bp,
        payouts_bp,
        pbgc_bp,
        forfeitures_bp,
        dlrs_bp,
        logs_bp,
        expenses_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_body(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_body(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_body(ERR_INVALID_REQUEST, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", f"internal error: {exc}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
