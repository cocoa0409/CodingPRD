"""Lab Equipment Sharing API — Flask entrypoint."""
import os

from flask import Flask

from errors import APIError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    from routes.system import bp as system_bp
    from routes.labs import bp as labs_bp
    from routes.users import bp as users_bp
    from routes.equipment import bp as equipment_bp
    from routes.billing_rules import bp as billing_rules_bp
    from routes.maintenance import bp as maintenance_bp
    from routes.authorizations import bp as authorizations_bp
    from routes.reservations import bp as reservations_bp
    from routes.audit_events import bp as audit_events_bp

    for bp in (system_bp, labs_bp, users_bp, equipment_bp, billing_rules_bp,
               maintenance_bp, authorizations_bp, reservations_bp,
               audit_events_bp):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Route or resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_BAD_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_BAD_REQUEST", str(e) or "Internal error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
