"""Bank Merger Application & Community Impact Review API.

Storage is in-memory only and starts empty on every boot: nothing is seeded.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.analyses import analyses_bp
from routes.applications import applications_bp
from routes.branches import branches_bp
from routes.clock import clock_bp
from routes.comments import comments_bp
from routes.conversions import conversions_bp
from routes.decisions import decisions_bp
from routes.hearings import hearings_bp
from routes.institutions import institutions_bp
from routes.markets import markets_bp
from routes.periods import periods_bp
from routes.plans import plans_bp
from routes.reports import reports_bp
from routes.schedules import schedules_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in (
        institutions_bp,
        markets_bp,
        branches_bp,
        applications_bp,
        schedules_bp,
        analyses_bp,
        periods_bp,
        comments_bp,
        hearings_bp,
        plans_bp,
        decisions_bp,
        conversions_bp,
        reports_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(exc):
        return error_response("ERR_INVALID_REQUEST", "malformed request", 400)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)

    @app.errorhandler(Exception)
    def _internal(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
        use_reloader=False,
    )
