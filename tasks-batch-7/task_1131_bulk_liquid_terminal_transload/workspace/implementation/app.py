"""Bulk Liquid Terminal API — Flask entry point.

Storage is in-memory only (db.STORE) and starts completely empty on every
boot: no seeding, no preloading, no external persistence. The logical clock
(clock.CLOCK) starts at exactly 2026-05-01T00:00:00Z on every boot.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.customers import bp as customers_bp
    from routes.tanks import bp as tanks_bp
    from routes.resources import bp as resources_bp
    from routes.leases import bp as leases_bp
    from routes.amendments import bp as amendments_bp
    from routes.allocations import bp as allocations_bp
    from routes.permits import bp as permits_bp
    from routes.movements import bp as movements_bp
    from routes.gauge_tickets import bp as gauge_tickets_bp
    from routes.samples import bp as samples_bp
    from routes.custody import bp as custody_bp
    from routes.statements import bp as statements_bp
    from routes.clock_routes import bp as clock_bp

    for bp in (customers_bp, tanks_bp, resources_bp, leases_bp, amendments_bp,
               allocations_bp, permits_bp, movements_bp, gauge_tickets_bp,
               samples_bp, custody_bp, statements_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify({
            "meta": {},
            "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found"},
        }), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify({
            "meta": {},
            "response_type": "error",
            "data": {"error_id": "ERR_METHOD_NOT_ALLOWED",
                     "message": "Method not allowed"},
        }), 405

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return jsonify({
            "meta": {},
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
        }), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
