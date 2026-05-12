"""Hotel Revenue Management API — Flask entrypoint."""
import os

from flask import Flask

from errors import APIError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    from routes.room_types import bp as room_types_bp
    from routes.rooms import bp as rooms_bp
    from routes.maintenance import bp as maintenance_bp
    from routes.channels import bp as channels_bp
    from routes.rate_plans import bp as rate_plans_bp
    from routes.rate_overrides import bp as rate_overrides_bp
    from routes.overbooking import bp as overbooking_bp
    from routes.reservations import bp as reservations_bp
    from routes.audit_logs import bp as audit_logs_bp
    from routes.system import bp as system_bp

    for bp in (room_types_bp, rooms_bp, maintenance_bp, channels_bp,
               rate_plans_bp, rate_overrides_bp, overbooking_bp,
               reservations_bp, audit_logs_bp, system_bp):
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
        return error_response("ERR_INVALID_INPUT", "Bad request", 422)

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_INPUT", str(e) or "Internal error", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
