"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.clock import bp as clock_bp
from routes.sites import bp as sites_bp
from routes.students import bp as students_bp
from routes.cycles import bp as cycles_bp
from routes.cases import bp as cases_bp
from routes.reviews import bp as reviews_bp
from routes.placements import bp as placements_bp
from routes.reevaluations import bp as reevaluations_bp
from routes.reports import bp as reports_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(sites_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(placements_bp)
    app.register_blueprint(reevaluations_bp)
    app.register_blueprint(reports_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, "malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Let ApiError pass through (handled above), otherwise 500 with the
        # standard envelope.
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
