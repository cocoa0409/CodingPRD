"""Trade Publication Circulation Audit API — entry point.

Storage is in-memory only and starts completely empty on every boot: no entity
is seeded, preloaded or hardcoded here or in any imported module.
"""
import os

from flask import Flask, jsonify

from envelope import error_body
from errors import ApiError, ERROR_HTTP
from routes_audit import audit_bp
from routes_commercial import commercial_bp
from routes_publications import publications_bp
from routes_requests import requests_bp
from routes_statements import statements_bp
from routes_subscribers import subscribers_bp
from routes_system import system_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(publications_bp)
    app.register_blueprint(subscribers_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(statements_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(commercial_bp)
    app.register_blueprint(system_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "No such resource.")), 404

    @app.errorhandler(405)
    def handle_405(exc):
        return jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed.")), 405

    @app.errorhandler(400)
    def handle_400(exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Malformed request.")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return jsonify(error_body(exc.error_id, exc.message)), exc.http_status
        status = getattr(exc, "code", None)
        if isinstance(status, int) and status in (404, 405, 400):
            return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), status
        return jsonify(error_body("ERR_INTERNAL", "Internal server error: %s" % exc)), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
