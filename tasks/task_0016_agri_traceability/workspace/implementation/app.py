"""Flask application entry point.

Listens on PORT env var (default 10000), bound to 0.0.0.0.
"""

import os
import traceback

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_NOT_FOUND, ERR_VALIDATION
from middleware import require_auth
from response import error_response, init_request

from routes.registry import bp as registry_bp
from routes.planting_batches import bp as planting_bp
from routes.storage_bins import bp as bins_bp
from routes.logistics import bp as logistics_bp
from routes.inspection import bp as inspection_bp
from routes.qr import bp as qr_bp
from routes.distributors import bp as distributors_bp
from routes.recalls import bp as recalls_bp
from routes.audit import bp as audit_bp
from routes.test_driver import bp as test_driver_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _before():
        init_request()
        if request.method == "OPTIONS":
            return None
        require_auth()

    @app.errorhandler(APIError)
    def _api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        status = err.code or 500
        if status == 404:
            return error_response(ERR_NOT_FOUND, err.description or "not found", 404)
        if status == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  err.description or "method not allowed", 405)
        if status == 400:
            return error_response(ERR_VALIDATION, err.description or "bad request", 400)
        return error_response("ERR_INTERNAL", err.description or "error", status)

    @app.errorhandler(Exception)
    def _generic(err):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", str(err), 500)

    app.register_blueprint(registry_bp)
    app.register_blueprint(planting_bp)
    app.register_blueprint(bins_bp)
    app.register_blueprint(logistics_bp)
    app.register_blueprint(inspection_bp)
    app.register_blueprint(qr_bp)
    app.register_blueprint(distributors_bp)
    app.register_blueprint(recalls_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(test_driver_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
