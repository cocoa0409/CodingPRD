"""Flask application entry point.

Listens on PORT env var (default 10000), bound to 0.0.0.0.
"""

import os
import traceback

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import require_auth
from response import error_response, init_request
from routes.audit_logs import bp as audit_bp
from routes.bids import bp as bids_bp
from routes.complaints import bp as complaints_bp
from routes.contracts import bp as contracts_bp
from routes.plans import bp as plans_bp
from routes.projects import bp as projects_bp
from routes.queries import bp as queries_bp
from routes.suppliers import bp as suppliers_bp
from routes.test_driver import bp as test_driver_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    # Flask 3.x uses app.json provider; older versions used the config flag.
    try:
        app.json.sort_keys = False
    except AttributeError:
        pass

    @app.before_request
    def _before():
        init_request()
        if request.method == "OPTIONS":
            return None
        require_auth()
        return None

    @app.errorhandler(APIError)
    def _api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        status = err.code or 500
        if status == 404:
            return error_response(ERR_NOT_FOUND, err.description or "not found", 404)
        if status == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED", err.description or "method not allowed", 405)
        if status == 400:
            return error_response(ERR_VALIDATION, err.description or "bad request", 422)
        return error_response("ERR_INTERNAL", err.description or "error", status)

    @app.errorhandler(Exception)
    def _generic(err):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", str(err), 500)

    app.register_blueprint(suppliers_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(bids_bp)
    app.register_blueprint(queries_bp)
    app.register_blueprint(complaints_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(test_driver_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
