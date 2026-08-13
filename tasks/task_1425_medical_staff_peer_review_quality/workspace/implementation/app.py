import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.providers import bp as providers_bp
from routes.members import bp as members_bp
from routes.cases import bp as cases_bp
from routes.assignments import bp as assignments_bp
from routes.focus import bp as focus_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(providers_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(focus_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(err):
        return error_response(ApiError("ERR_VALIDATION", 404, "route not found"))

    @app.errorhandler(405)
    def _handle_405(err):
        return error_response(ApiError("ERR_VALIDATION", 405, "method not allowed"))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return error_response(ApiError("ERR_VALIDATION", 500, "internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
