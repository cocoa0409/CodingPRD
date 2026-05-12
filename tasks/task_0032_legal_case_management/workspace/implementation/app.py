"""Legal Case Management API — Flask entry point.

Implements the REST API described in workspace/PRD.md and SCAFFOLD.yaml.
The server listens on the PORT env var (default 10000), bound to 0.0.0.0.
"""

import os

from flask import Flask, jsonify

import errors
import response
from routes.lawyers import bp as lawyers_bp
from routes.cases import bp as cases_bp
from routes.parties import bp as parties_bp
from routes.document_templates import bp as document_templates_bp
from routes.document_drafts import bp as document_drafts_bp
from routes.hearings import bp as hearings_bp
from routes.evidence import bp as evidence_bp
from routes.time_entries import bp as time_entries_bp
from routes.bills import bp as bills_bp
from routes.events import bp as events_bp
from routes.audit_logs import bp as audit_logs_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(lawyers_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(document_templates_bp)
    app.register_blueprint(document_drafts_bp)
    app.register_blueprint(hearings_bp)
    app.register_blueprint(evidence_bp)
    app.register_blueprint(time_entries_bp)
    app.register_blueprint(bills_bp)
    app.register_blueprint(events_bp)
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
