"""Flask application factory + routes registration + error handlers."""

from __future__ import annotations

from flask import Flask, request

from envelope import error_response, success
from errors import APIError
from ids import new_request_id


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _attach_request_id():
        request.api_request_id = new_request_id()

    @app.errorhandler(APIError)
    def _handle_api_error(err: APIError):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(_e):
        return error_response(APIError("ERR_NOT_FOUND", "No such route."))

    @app.errorhandler(405)
    def _handle_405(_e):
        return error_response(APIError("ERR_NOT_FOUND", "Method not allowed."))

    @app.errorhandler(400)
    def _handle_400(_e):
        return error_response(APIError("ERR_VALIDATION", "Malformed request."))

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        # Surface internal errors as ERR_VALIDATION rather than exposing tracebacks.
        return error_response(APIError("ERR_VALIDATION", f"Internal error: {e!s}"))

    # Health endpoint for readiness probes.
    @app.route("/")
    def _root():
        return success({"service": "food-delivery-api", "status": "ok"})

    # Import + register route modules (each module exposes `register(app)`)
    from routes_restaurants import register as register_restaurants
    from routes_menu_items import register as register_menu_items
    from routes_riders import register as register_riders
    from routes_customers import register as register_customers
    from routes_orders import register as register_orders
    from routes_assignments import register as register_assignments
    from routes_returns import register as register_returns
    from routes_workorders import register as register_workorders
    from routes_fines import register as register_fines
    from routes_clock import register as register_clock

    register_restaurants(app)
    register_menu_items(app)
    register_riders(app)
    register_customers(app)
    register_orders(app)
    register_assignments(app)
    register_returns(app)
    register_workorders(app)
    register_fines(app)
    register_clock(app)

    return app
