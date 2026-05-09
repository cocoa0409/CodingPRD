"""Flask application entry point.

Listens on PORT env var (default 10000), bound to 0.0.0.0.
"""

import os
import traceback

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_INPUT
from middleware import require_auth
from response import error_response, init_request
from routes.allocation_runs import bp as allocation_bp
from routes.audit_logs import bp as audit_logs_bp
from routes.budget_adjustments import bp as budget_adj_bp
from routes.budget_items import bp as budget_items_bp
from routes.closing_audits import bp as closing_audits_bp
from routes.compliance_rules import bp as compliance_bp
from routes.projects import bp as projects_bp
from routes.reimbursements import bp as reimbursements_bp
from routes.test_driver import bp as test_driver_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _before():
        init_request()
        # Skip auth on health/options endpoints if any (none defined; auth always required)
        if request.method == "OPTIONS":
            return None
        require_auth()

    @app.errorhandler(APIError)
    def _api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        # Map werkzeug HTTPException — most relevant: 404 (no route), 405, 400 (bad json)
        status = err.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", err.description or "not found", 404)
        if status == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED", err.description or "method not allowed", 405)
        if status == 400:
            return error_response(ERR_INVALID_INPUT, err.description or "bad request", 400)
        return error_response("ERR_INTERNAL", err.description or "error", status)

    @app.errorhandler(Exception)
    def _generic(err):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", str(err), 500)

    app.register_blueprint(projects_bp)
    app.register_blueprint(budget_items_bp)
    app.register_blueprint(budget_adj_bp)
    app.register_blueprint(reimbursements_bp)
    app.register_blueprint(closing_audits_bp)
    app.register_blueprint(compliance_bp)
    app.register_blueprint(allocation_bp)
    app.register_blueprint(audit_logs_bp)
    app.register_blueprint(test_driver_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
