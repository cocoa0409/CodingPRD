"""Flask entry point: error handlers, route registration, server boot."""
import os
import sys

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", "Resource not found at the specified path", 404)

    @app.errorhandler(405)
    def _method(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def _unhandled(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return error_response("ERR_INVALID_REQUEST", e.description or "Bad request", 400)
        print(f"Unhandled: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "Internal error", 400)

    from routes.clock import bp as clock_bp
    from routes.customers import bp as customers_bp
    from routes.board_grades import bp as board_grades_bp
    from routes.box_orders import bp as box_orders_bp
    from routes.quotes import bp as quotes_bp
    from routes.work_shifts import bp as work_shifts_bp
    from routes.corrugator_runs import bp as corrugator_runs_bp
    from routes.converting_bookings import bp as converting_bookings_bp
    from routes.inventory_programs import bp as inventory_programs_bp
    from routes.quality_claims import bp as quality_claims_bp

    for bp in (
        clock_bp,
        customers_bp,
        board_grades_bp,
        box_orders_bp,
        quotes_bp,
        work_shifts_bp,
        corrugator_runs_bp,
        converting_bookings_bp,
        inventory_programs_bp,
        quality_claims_bp,
    ):
        app.register_blueprint(bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
