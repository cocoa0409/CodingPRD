"""Blueprint registration."""

from flask import Blueprint, request, g

from middleware import authenticate
from errors import AppError, ERR_INVALID_INPUT


def register_routes(app):
    from routes.exhibitions import bp as exhibitions_bp
    from routes.halls import bp as halls_bp
    from routes.applications import bp as applications_bp
    from routes.allocations import bp as allocations_bp
    from routes.dock_slots import bp as dock_bp
    from routes.work_orders import bp as wo_bp
    from routes.tickets import bp as tickets_bp
    from routes.entitlements import bp as ent_bp
    from routes.clock_routes import bp as clock_bp

    @app.before_request
    def _auth():
        # All endpoints require auth; flask handles 404 itself for unknown routes,
        # but we still need to authenticate for known routes.
        # Test-isolation endpoint is unauthenticated (not in PRD).
        if request.path == "/__test__/reset":
            return
        authenticate()

    @app.before_request
    def _parse_json():
        # Pre-parse JSON body once. Tolerate empty bodies and malformed JSON.
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                g.body = request.get_json(silent=True) or {}
            except Exception:
                g.body = {}
            if g.body is None:
                g.body = {}
        else:
            g.body = {}

    for bp in (
        clock_bp,
        exhibitions_bp,
        halls_bp,
        applications_bp,
        allocations_bp,
        dock_bp,
        wo_bp,
        tickets_bp,
        ent_bp,
    ):
        app.register_blueprint(bp)
