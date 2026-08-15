"""Service Dog Placement API — Flask entry point."""
import os

from flask import Flask, jsonify

from core import ApiError, _meta, respond_error
from routes_aftercare import bp as aftercare_bp
from routes_intake import bp as intake_bp
from routes_match import bp as match_bp
from routes_program import bp as program_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(intake_bp)
    app.register_blueprint(program_bp)
    app.register_blueprint(match_bp)
    app.register_blueprint(aftercare_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return respond_error(err)

    @app.errorhandler(404)
    def handle_404(err):
        return respond_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return respond_error(
            ApiError("ERR_NOT_FOUND", 404, "Method not allowed on this resource")
        )

    @app.errorhandler(400)
    def handle_400(err):
        return respond_error(ApiError("ERR_VALIDATION", 400, "Malformed request"))

    @app.errorhandler(Exception)
    def handle_generic(err):
        if isinstance(err, ApiError):
            return respond_error(err)
        return respond_error(ApiError("ERR_VALIDATION", 400, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
