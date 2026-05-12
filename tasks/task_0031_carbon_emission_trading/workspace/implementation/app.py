"""Carbon Emission Trading API — Flask entry point.

Implements the REST API described in PRD.md / SCAFFOLD.yaml. The server listens
on the PORT env var (default 10000), bound to 0.0.0.0.
"""

import os

from flask import Flask, jsonify

import errors
import response
from routes.enterprises import bp as enterprises_bp
from routes.allocation_cycles import bp as allocation_cycles_bp
from routes.emission_reports import bp as emission_reports_bp
from routes.trading import bp as trading_bp
from routes.compliance import bp as compliance_bp
from routes.audit_logs import bp as audit_logs_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(enterprises_bp)
    app.register_blueprint(allocation_cycles_bp)
    app.register_blueprint(emission_reports_bp)
    app.register_blueprint(trading_bp)
    app.register_blueprint(compliance_bp)
    app.register_blueprint(audit_logs_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(errors.APIError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_exc):
        return response.error(errors.ERR_NOT_FOUND, 404, "Path not found.")

    @app.errorhandler(405)
    def handle_405(_exc):
        return response.error(errors.ERR_NOT_FOUND, 404, "Method not allowed for this path.")

    @app.errorhandler(Exception)
    def handle_uncaught(exc):
        # Treat any unanticipated bug as a 500 with a basic envelope.
        body = {
            "meta": {
                "api_request_id": "req_INTERNAL",
                "api_request_timestamp": "",
            },
            "response_type": "error",
            "data": {
                "error_id": "ERR_INTERNAL",
                "message": str(exc),
            },
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
