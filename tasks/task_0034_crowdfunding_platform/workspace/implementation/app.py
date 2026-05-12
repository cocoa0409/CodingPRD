"""Crowdfunding Platform API — Flask entry point."""

import os

from flask import Flask, request

from errors import APIError, auth_required, forbidden
from middleware import VALID_ROLES, extract_auth
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    # Make the JSON output deterministic where possible.
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    # Endpoints that bypass auth (none in this scaffold beyond healthz)
    OPEN_PATHS = {"/healthz", "/_health"}

    @app.before_request
    def _auth_check():
        if request.method == "OPTIONS":
            return None
        path = request.path
        if path in OPEN_PATHS:
            return None
        # Auth headers required for every other endpoint
        try:
            extract_auth()
        except APIError as exc:
            return error_response(exc.error_id, exc.message, exc.http_status)
        return None

    # Register blueprints
    from routes.initiators import bp as initiators_bp
    from routes.backers import bp as backers_bp
    from routes.projects import bp as projects_bp
    from routes.rewards import bp as rewards_bp
    from routes.addons import bp as addons_bp
    from routes.orders import bp as orders_bp
    from routes.progress import bp as progress_bp
    from routes.refunds import bp as refunds_bp
    from routes.settlement import bp as settlement_bp
    from routes.audit import bp as audit_bp
    from routes.events import bp as events_bp

    app.register_blueprint(initiators_bp)
    app.register_blueprint(backers_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(rewards_bp)
    app.register_blueprint(addons_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(progress_bp)
    app.register_blueprint(refunds_bp)
    app.register_blueprint(settlement_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(events_bp)

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
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _on_uncaught(exc):
        # Surface unexpected errors as 500 with a generic envelope so tests get a
        # parsable JSON body rather than HTML.
        if isinstance(exc, APIError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", f"Internal server error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Bind to 0.0.0.0 per INSTRUCTION.md
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
