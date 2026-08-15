"""Sports Medicine & Athlete Availability API — Flask entry point."""
import os

from flask import Flask

from db import LOCK
from errors import ApiError, ERR_NOT_FOUND
from response import error_response

PREFIX = "/sports-med"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.teams import bp as teams_bp
    from routes.athletes import bp as athletes_bp
    from routes.cases import bp as cases_bp
    from routes.rtp import bp as rtp_bp
    from routes.workload import bp as workload_bp
    from routes.billing import bp as billing_bp
    from routes.reports import bp as reports_bp

    for bp in (teams_bp, athletes_bp, cases_bp, rtp_bp,
               workload_bp, billing_bp, reports_bp):
        app.register_blueprint(bp, url_prefix=PREFIX)

    @app.before_request
    def _acquire():
        LOCK.acquire()

    @app.teardown_request
    def _release(exc):
        try:
            LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(Exception)
    def _unhandled(err):
        return error_response(err)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
