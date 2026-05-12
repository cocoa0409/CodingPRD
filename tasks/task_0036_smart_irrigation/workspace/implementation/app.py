"""Smart Irrigation API — Flask entry point."""

import os

from flask import Flask, request

from errors import APIError
from middleware import extract_auth
from response import error_response


# Test-driving endpoints bypass auth per PRD §2.1.
OPEN_PATHS = {
    "/_clock/advance",
    "/_sweep/run",
    "/_events/emit",
    "/healthz",
    "/_health",
}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth_check():
        if request.method == "OPTIONS":
            return None
        path = request.path
        if path in OPEN_PATHS:
            return None
        try:
            extract_auth()
        except APIError as exc:
            return error_response(exc.error_id, exc.message, exc.http_status)
        return None

    # Register blueprints
    from routes.tenants import bp as tenants_bp
    from routes.plots import bp as plots_bp
    from routes.sensors import bp as sensors_bp
    from routes.irrigation_plans import bp as plans_bp
    from routes.valve_groups import bp as valve_groups_bp
    from routes.control_commands import bp as commands_bp
    from routes.water_quotas import bp as quotas_bp
    from routes.alerts import bp as alerts_bp
    from routes.water_bills import bp as bills_bp
    from routes.audit import bp as audit_bp
    from routes.test_driving import bp as test_bp

    app.register_blueprint(tenants_bp)
    app.register_blueprint(plots_bp)
    app.register_blueprint(sensors_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(valve_groups_bp)
    app.register_blueprint(commands_bp)
    app.register_blueprint(quotas_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(bills_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(test_bp)

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
        return error_response("ERR_VALIDATION", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _on_uncaught(exc):
        if isinstance(exc, APIError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_VALIDATION", f"Internal server error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
