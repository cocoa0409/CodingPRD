"""Flask application factory."""
from __future__ import annotations

from flask import Flask, Response, g, request

from .auth import parse_headers
from .envelope import error_response
from .errors import ApiError
from .store import Store


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    store = Store()
    app.config["STORE"] = store

    @app.before_request
    def _attach_store_and_auth():
        g.store = store
        # Auth is required for every /api endpoint. Anything outside /api is
        # treated as 404 to keep the surface tight.
        if not request.path.startswith("/api"):
            return None
        # The clock-advance endpoint and every other /api endpoint require auth.
        user_id, user_role = parse_headers()
        g.user_id = user_id
        g.user_role = user_role
        return None

    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        return error_response(store.clock, err.error_id, err.message, err.status)

    @app.errorhandler(404)
    def _handle_404(_err):
        return error_response(store.clock, "ERR_NOT_FOUND", "route not found", 404)

    @app.errorhandler(405)
    def _handle_405(_err):
        # Per PRD, only the documented error codes are used. A method on a known
        # path that has no handler is best surfaced as ERR_NOT_FOUND.
        return error_response(store.clock, "ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def _handle_400(_err):
        return error_response(store.clock, "ERR_VALIDATION", "malformed request", 422)

    @app.errorhandler(500)
    def _handle_500(err):
        return error_response(store.clock, "ERR_VALIDATION", f"internal error: {err}", 500)

    # Register all blueprints.
    from .routes import (
        restaurants,
        menu_items,
        riders,
        customers,
        orders,
        assignments,
        returns_,
        fines,
        work_orders,
        clock as clock_routes,
    )

    app.register_blueprint(restaurants.bp)
    app.register_blueprint(menu_items.bp)
    app.register_blueprint(riders.bp)
    app.register_blueprint(customers.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(assignments.bp)
    app.register_blueprint(returns_.bp)
    app.register_blueprint(fines.bp)
    app.register_blueprint(work_orders.bp)
    app.register_blueprint(clock_routes.bp)

    return app
