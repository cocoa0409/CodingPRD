"""Entry point: Flask app assembly, error handlers, route registration."""
import os
import traceback

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import err


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.periods import bp as periods_bp
    from routes.operators import bp as operators_bp
    from routes.runs import bp as runs_bp
    from routes.bids import bp as bids_bp
    from routes.assignments import bp as assignments_bp
    from routes.absences import bp as absences_bp
    from routes.vacation import bp as vacation_bp
    from routes.grievances import bp as grievances_bp

    for blueprint in (
        periods_bp,
        operators_bp,
        runs_bp,
        bids_bp,
        assignments_bp,
        absences_bp,
        vacation_bp,
        grievances_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return err(ERR_NOT_FOUND, "Path-referenced resource does not exist", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return err(ERR_NOT_FOUND, "Method not allowed for this path", 405)

    @app.errorhandler(400)
    def handle_400(e):
        return err(ERR_VALIDATION, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_generic(e):
        traceback.print_exc()
        return err("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
