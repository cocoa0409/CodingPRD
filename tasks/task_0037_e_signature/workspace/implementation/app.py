"""E-Signature API — Flask entry point."""

import os

from flask import Flask, request

from errors import APIError, unauthenticated
from middleware import extract_auth
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    # Endpoints that bypass auth: health checks and the test-fixture reset/seed.
    OPEN_PATHS = {"/healthz", "/_health", "/_reset", "/_org-users"}

    @app.before_request
    def _auth_check():
        if request.method == "OPTIONS":
            return None
        path = request.path
        if path in OPEN_PATHS or path.startswith("/_org-users"):
            return None
        try:
            extract_auth()
        except APIError as exc:
            return error_response(exc.error_id, exc.message, exc.http_status)
        return None

    # Register blueprints
    from routes.templates import bp as templates_bp
    from routes.contracts import bp as contracts_bp
    from routes.signing import bp as signing_bp
    from routes.identity import bp as identity_bp
    from routes.reminders import bp as reminders_bp
    from routes.evidence import bp as evidence_bp
    from routes.system import bp as system_bp

    app.register_blueprint(templates_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(signing_bp)
    app.register_blueprint(identity_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(evidence_bp)
    app.register_blueprint(system_bp)

    @app.route("/healthz", methods=["GET"])
    def _healthz():
        return {"status": "ok"}, 200

    @app.errorhandler(APIError)
    def _on_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _on_404(_e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _on_405(_e):
        return error_response("ERR_VALIDATION_FAILED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _on_uncaught(exc):
        if isinstance(exc, APIError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_VALIDATION_FAILED", f"Internal error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
