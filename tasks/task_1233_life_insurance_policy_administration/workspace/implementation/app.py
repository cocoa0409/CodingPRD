"""Life Insurance Policy Administration API — Flask entry point.

The in-memory store starts empty on every boot; the logical clock starts at
2026-05-01T00:00:00Z. See PRD.md / SCAFFOLD.yaml for the full contract.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.core import bp as core_bp
    from routes.applications import bp as applications_bp
    from routes.policies import bp as policies_bp
    from routes.loans import bp as loans_bp
    from routes.dividends_elections import bp as dividends_bp
    from routes.reinstatements import bp as reinstatements_bp
    from routes.riders import bp as riders_bp
    from routes.conversions import bp as conversions_bp
    from routes.listings import bp as listings_bp

    for bp in (core_bp, applications_bp, policies_bp, loans_bp, dividends_bp,
               reinstatements_bp, riders_bp, conversions_bp, listings_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INVALID_REQUEST", 400, str(err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
