import os

from flask import Flask

import response
from errors import ApiError, ERR_NOT_FOUND

from routes.clock_routes import bp as clock_bp
from routes.circuits import bp as circuits_bp
from routes.windows import bp as windows_bp
from routes.jobs import bp as jobs_bp
from routes.permits import bp as permits_bp
from routes.series import bp as series_bp
from routes.faults import bp as faults_bp
from routes.excavations import bp as excavations_bp
from routes.splices import bp as splices_bp
from routes.units import bp as units_bp
from routes.assignments import bp as assignments_bp
from routes.assessments import bp as assessments_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        clock_bp, circuits_bp, windows_bp, jobs_bp, permits_bp, series_bp,
        faults_bp, excavations_bp, splices_bp, units_bp, assignments_bp,
        assessments_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err)

    @app.errorhandler(404)
    def handle_404(err):
        return response.error(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return response.error(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return response.error(ApiError("ERR_INTERNAL", 500, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
