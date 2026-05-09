import os
from flask import Flask, request
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_INVALID_INPUT, ERR_NOT_FOUND
from auth import require_auth, VALID_ROLES

# Routes
from routes.cabinets import bp as cabinets_bp
from routes.devices import bp as devices_bp
from routes.pricing_plans import bp as pricing_bp
from routes.users import bp as users_bp
from routes.rentals import bp as rentals_bp
from routes.repair_tickets import bp as repair_bp
from routes.operator_tasks import bp as op_tasks_bp
from routes.settlements import bp as settlements_bp
from routes.location_partners import bp as partners_bp
from routes.maintenance_windows import bp as maintenance_bp
from routes.payment_events import bp as payment_bp
from routes.test_endpoints import bp as test_bp


# Endpoints exempt from auth (PRD §2.1.1).
NO_AUTH_PREFIXES = ("/payment-events", "/_clock/advance", "/_sweep/run", "/_events/emit", "/_state/reset")


def create_app() -> Flask:
    app = Flask(__name__)
    # Preserve key order in JSON responses so envelope reads naturally.
    app.json.sort_keys = False

    @app.before_request
    def _enforce_auth_priority_1_2():
        # Skip for unauth-exempt endpoints.
        path = request.path
        if any(path.startswith(p) for p in NO_AUTH_PREFIXES):
            return None
        # Skip for OPTIONS / Werkzeug-internal paths.
        if request.method == "OPTIONS":
            return None
        # Priority 1.
        require_auth()
        # Priority 2 is enforced per-endpoint via require_role(allowed). However, if the role
        # value is utterly malformed (not a known token) we can short-circuit:
        role = request.headers.get("X-User-Role")
        if role not in VALID_ROLES:
            from errors import APIError
            raise APIError(ERR_FORBIDDEN, 403, "Unknown role")
        return None

    # Register blueprints.
    app.register_blueprint(cabinets_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(pricing_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(rentals_bp)
    app.register_blueprint(repair_bp)
    app.register_blueprint(op_tasks_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(partners_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(test_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(err: APIError):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(err: HTTPException):
        if err.code == 404:
            return error_response(APIError(ERR_NOT_FOUND, 404, "Resource not found"))
        if err.code == 405:
            return error_response(APIError(ERR_NOT_FOUND, 404, "Resource not found"))
        if err.code == 400:
            return error_response(APIError(ERR_INVALID_INPUT, 400, err.description or "Bad request"))
        return error_response(APIError("ERR_INVALID_INPUT", err.code or 500, err.description or "Error"))

    @app.errorhandler(Exception)
    def _handle_generic(err: Exception):
        return error_response(APIError("ERR_INVALID_INPUT", 500, str(err) or "Internal server error"))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
