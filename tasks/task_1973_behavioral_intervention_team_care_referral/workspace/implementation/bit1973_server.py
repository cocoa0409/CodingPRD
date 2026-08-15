import os

from flask import Flask

import errors as E
import response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.students import bp as students_bp
    from routes.staff import bp as staff_bp
    from routes.reports import bp as reports_bp
    from routes.cases import bp as cases_bp
    from routes.scorings import bp as scorings_bp
    from routes.plans import bp as plans_bp
    from routes.assessments import bp as assessments_bp
    from routes.leave_decisions import bp as leave_decisions_bp
    from routes.reentries import bp as reentries_bp
    from routes.checkins import bp as checkins_bp
    from routes.grants import bp as grants_bp
    from routes.trends import bp as trends_bp
    from routes.clock import bp as clock_bp

    for bp in (
        students_bp,
        staff_bp,
        reports_bp,
        cases_bp,
        scorings_bp,
        plans_bp,
        assessments_bp,
        leave_decisions_bp,
        reentries_bp,
        checkins_bp,
        grants_bp,
        trends_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.err(e)

    @app.errorhandler(404)
    def handle_404(e):
        return response.err(ApiError(E.ERR_NOT_FOUND, 404, "resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return response.err(ApiError(E.ERR_NOT_FOUND, 405, "method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return response.err(ApiError(E.ERR_VALIDATION, 500, f"internal error: {e}"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
