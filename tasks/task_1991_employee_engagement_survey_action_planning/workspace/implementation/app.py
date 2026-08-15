"""Engagement Survey API — Flask entry point.

Mounts every route module under /engagement, registers the error envelope
handler, and runs the server on 0.0.0.0:$PORT (default 10000). The store is
purely in-memory and starts empty on every boot; nothing is seeded.
"""

import os

from flask import Flask

from errors import ApiError, err, ERR_VALIDATION, ERR_NOT_FOUND
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.item_banks import bp as item_banks_bp
    from routes.org_units import bp as org_units_bp
    from routes.employees import bp as employees_bp
    from routes.cycles import bp as cycles_bp
    from routes.invites import bp as invites_bp
    from routes.snapshots import bp as snapshots_bp
    from routes.action_plans import bp as action_plans_bp
    from routes.outcomes import bp as outcomes_bp
    from routes.clock import bp as clock_bp

    app.register_blueprint(item_banks_bp)
    app.register_blueprint(org_units_bp)
    app.register_blueprint(employees_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(invites_bp)
    app.register_blueprint(snapshots_bp)
    app.register_blueprint(action_plans_bp)
    app.register_blueprint(outcomes_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(ERR_VALIDATION, "malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
