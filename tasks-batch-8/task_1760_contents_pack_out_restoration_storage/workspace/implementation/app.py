"""Flask application entry point."""

import os
from flask import Flask

from errors import ApiError, not_found, validation
from response import error as error_response

from routes.jobs import bp as jobs_bp
from routes.items import bp as items_bp
from routes.disposal import bp as disposal_bp
from routes.cleaning import bp as cleaning_bp
from routes.vaults import bp as vaults_bp
from routes.placements import bp as placements_bp
from routes.subcontractors import bp as subcontractors_bp
from routes.referrals import bp as referrals_bp
from routes.claims import bp as claims_bp
from routes.schedules import bp as schedules_bp
from routes.billing import bp as billing_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        jobs_bp,
        items_bp,
        disposal_bp,
        cleaning_bp,
        vaults_bp,
        placements_bp,
        subcontractors_bp,
        referrals_bp,
        claims_bp,
        schedules_bp,
        billing_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(not_found("Route not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(not_found("Method not allowed"))

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(validation("Malformed request"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        import traceback
        traceback.print_exc()
        return error_response(validation(f"Internal error: {err}"))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
