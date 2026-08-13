"""Flask entry point: auth before-request, blueprints, error handlers."""
import os

from flask import Flask, request

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from middleware import authenticate
from response import error_response, success_object


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth():
        if request.path.startswith("/credit"):
            authenticate()

    from routes import (
        officers, borrowers, applications, statements, exceptions, appraisals,
        committee, termsheets, letters, checklist, funding, covenants,
        participations, clock,
    )
    for module in (officers, borrowers, applications, statements, exceptions,
                   appraisals, committee, termsheets, letters, checklist,
                   funding, covenants, participations, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response(ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Resource not found."))

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response(ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1], "Method not allowed."))

    @app.errorhandler(500)
    def _internal_error(err):
        return error_response(ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1], "Internal server error."))

    @app.get("/")
    def root():
        return success_object({"service": "commercial-loan-origination"})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
