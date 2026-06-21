"""Flask entry point: blueprint registration + error handlers.

The in-memory store starts EMPTY on every boot. No entity is seeded here or in
any imported module — every entity is built by a test via the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.onboardings import bp as onboardings_bp
from routes.identity_documents import bp as identity_documents_bp
from routes.i9_forms import bp as i9_forms_bp
from routes.reverification_events import bp as reverification_events_bp
from routes.everify_cases import bp as everify_cases_bp
from routes.work_authorizations import bp as work_authorizations_bp
from routes.audit_entries import bp as audit_entries_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(onboardings_bp)
    app.register_blueprint(identity_documents_bp)
    app.register_blueprint(i9_forms_bp)
    app.register_blueprint(reverification_events_bp)
    app.register_blueprint(everify_cases_bp)
    app.register_blueprint(work_authorizations_bp)
    app.register_blueprint(audit_entries_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Unmatched route / method => surface as the catalog's not-found / generic.
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return error_response("ERR_NOT_FOUND",
                                  "Method not allowed for this path", 404)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  exc.description or "Bad request", 400)
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "Request error",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Last-resort guard so an internal bug never breaks the response envelope.
        return error_response("ERR_INVALID_REQUEST",
                              "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
