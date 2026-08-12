"""Health Plan Provider Contracting & Fee Schedule Load API.

Flask entry point: registers all route blueprints and error handlers.
Storage is in-memory only (see store.py); nothing is seeded at startup.
"""

import os

from flask import Flask

from envelope import error_resp
from errors import ApiError


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    from views_audit import bp as audit_bp
    from views_carveouts import bp as carveouts_bp
    from views_contracts import bp as contracts_bp
    from views_entries import bp as entries_bp
    from views_providers import bp as providers_bp
    from views_reference import bp as reference_bp
    from views_retro import bp as retro_bp
    from views_simulation import bp as simulation_bp
    from views_termination import bp as termination_bp
    from views_versions import bp as versions_bp

    for blueprint in (
        reference_bp, providers_bp, contracts_bp, versions_bp, entries_bp,
        carveouts_bp, simulation_bp, retro_bp, termination_bp, audit_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_resp(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_resp(ApiError("ERR_NOT_FOUND", 404, "Resource not found."))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_resp(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed."))

    @app.errorhandler(Exception)
    def handle_internal(err):
        if isinstance(err, ApiError):
            return error_resp(err)
        return error_resp(ApiError("ERR_INTERNAL", 500, "Internal server error."))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
