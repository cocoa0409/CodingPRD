"""LTC Insurance Administration API — entry point."""
import os

from flask import Flask

import errors
from response import error_response
from db import LOCK

from routes.policyholders import bp as policyholders_bp
from routes.policies import bp as policies_bp
from routes.benefit import bp as benefit_bp
from routes.premium import bp as premium_bp
from routes.rate_filings import bp as rate_filings_bp
from routes.triggers import bp as triggers_bp
from routes.providers import bp as providers_bp
from routes.care_plans import bp as care_plans_bp
from routes.claims import bp as claims_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Serialize all requests so cascades stay atomic relative to each other.
    @app.before_request
    def _acquire_lock():
        LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc):
        try:
            LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(errors.ApiError)
    def _handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INTERNAL", str(e), 500)

    for bp in (policyholders_bp, policies_bp, benefit_bp, premium_bp, rate_filings_bp,
               triggers_bp, providers_bp, care_plans_bp, claims_bp, clock_bp):
        app.register_blueprint(bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
