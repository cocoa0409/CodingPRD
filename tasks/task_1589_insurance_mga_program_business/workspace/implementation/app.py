"""Flask entry point: auth before-request, blueprints, error handlers."""
import os

from flask import Flask, request

from errors import ApiError, ERR_NOT_FOUND, ERR_INTERNAL
from middleware import authenticate
from response import error_response, success_object


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    @app.before_request
    def _auth():
        # Pipeline stage 1 runs before dispatch, so even unmatched /mga paths
        # require authentication first.
        if request.path.startswith("/mga"):
            authenticate()

    from routes import (
        carriers, programs, guidelines, allocations, filings, policies,
        trust, claims, appointments, bordereaux, audits, evaluations, ops,
    )
    for module in (carriers, programs, guidelines, allocations, filings,
                   policies, trust, claims, appointments, bordereaux, audits,
                   evaluations, ops):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Referenced resource does not exist."))

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Referenced resource does not exist."))

    @app.errorhandler(Exception)
    def _unexpected(e):
        return error_response(ApiError(ERR_INTERNAL[0], ERR_INTERNAL[1], "Internal server error."))

    @app.get("/")
    def root():
        return success_object({"service": "insurance-mga-program-business"})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
