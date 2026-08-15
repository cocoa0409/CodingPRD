"""FSA Farm Program Enrollment API — Flask entry point.

Storage is in-memory only (Python dicts in db.py). The store starts empty
on every boot; no seeding, preloading, or hardcoded entities.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.farms import bp as farms_bp
    from routes.producers import bp as producers_bp
    from routes.memberships import bp as memberships_bp
    from routes.tracts import bp as tracts_bp
    from routes.reconstitutions import bp as reconstitutions_bp
    from routes.acreage_reports import bp as acreage_reports_bp
    from routes.elections import bp as elections_bp
    from routes.yields import bp as yields_bp
    from routes.enrollments import bp as enrollments_bp
    from routes.disasters import bp as disasters_bp
    from routes.appeals import bp as appeals_bp
    from routes.clock_routes import bp as clock_bp

    for bp in (farms_bp, producers_bp, memberships_bp, tracts_bp,
               reconstitutions_bp, acreage_reports_bp, elections_bp,
               yields_bp, enrollments_bp, disasters_bp, appeals_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, "Malformed request", 400)

    @app.errorhandler(500)
    def handle_500(err):
        return error_response(ERR_INVALID_REQUEST, "Internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
