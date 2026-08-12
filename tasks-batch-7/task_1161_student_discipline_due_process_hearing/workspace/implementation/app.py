"""Entry point: Flask app assembly, error handlers, route registration."""
import os

from flask import Flask
from werkzeug.exceptions import BadRequest, NotFound, MethodNotAllowed

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.clock import bp as clock_bp
from routes.students import bp as students_bp
from routes.offense_codes import bp as offense_codes_bp
from routes.cases import bp as cases_bp
from routes.conferences import bp as conferences_bp
from routes.appeals import bp as appeals_bp
from routes.hearings import bp as hearings_bp
from routes.mdr import bp as mdr_bp
from routes.alt_ed import bp as alt_ed_bp
from routes.reentry import bp as reentry_bp
from routes.expungement import bp as expungement_bp
from routes.reports import bp as reports_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        students_bp,
        offense_codes_bp,
        cases_bp,
        conferences_bp,
        appeals_bp,
        hearings_bp,
        mdr_bp,
        alt_ed_bp,
        reentry_bp,
        expungement_bp,
        reports_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(NotFound)
    def handle_not_found(err):
        return error_response(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "resource not found")

    @app.errorhandler(MethodNotAllowed)
    def handle_method_not_allowed(err):
        return error_response(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "method not allowed")

    @app.errorhandler(BadRequest)
    def handle_bad_request(err):
        return error_response(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "malformed request")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", 500, str(err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
