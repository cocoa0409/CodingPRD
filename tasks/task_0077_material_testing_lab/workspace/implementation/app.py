"""Material Testing Lab API — Flask entry point."""

import os
from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound, MethodNotAllowed

from errors import APIError
from response import error_response

from routes.clients import bp as clients_bp
from routes.testers import bp as testers_bp
from routes.reviewers import bp as reviewers_bp
from routes.signatories import bp as signatories_bp
from routes.instruments import bp as instruments_bp
from routes.samples import bp as samples_bp
from routes.tasks import bp as tasks_bp
from routes.records import bp as records_bp
from routes.reports import bp as reports_bp
from routes.invoices import bp as invoices_bp
from routes.audit import bp as audit_bp
from routes.system import bp as system_bp


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    app.register_blueprint(clients_bp)
    app.register_blueprint(testers_bp)
    app.register_blueprint(reviewers_bp)
    app.register_blueprint(signatories_bp)
    app.register_blueprint(instruments_bp)
    app.register_blueprint(samples_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(records_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(system_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(NotFound)
    def _handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(MethodNotAllowed)
    def _handle_405(err):
        return error_response("ERR_VALIDATION", 422, "Method not allowed")

    @app.errorhandler(HTTPException)
    def _handle_http_error(err):
        status = err.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", 404, err.description or "Not found")
        if status == 400:
            return error_response("ERR_VALIDATION", 422, err.description or "Bad request")
        return error_response("ERR_VALIDATION", status if status >= 400 else 422,
                              err.description or "HTTP error")

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return error_response("ERR_VALIDATION", 500, f"Internal error: {err}")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
