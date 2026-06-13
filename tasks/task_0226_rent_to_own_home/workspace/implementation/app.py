"""Rent-to-Own / Lease-Purchase Home API — Flask entry point.

In-memory storage only (see db.py). No seeding at startup: the store begins
empty and every entity is created by tests via the declared API surface. Boot
is fresh on every process launch, which is what per-test-server isolation
relies on.
"""

import os

from flask import Flask, g

import db
from errors import ApiError
from response import error_response

# Route blueprints.
from routes.parties import bp as parties_bp
from routes.properties import bp as properties_bp
from routes.agreements import bp as agreements_bp
from routes.rent_payments import bp as rent_payments_bp
from routes.maintenance import bp as maintenance_bp
from routes.option_exercises import bp as option_exercises_bp
from routes.mortgages import bp as mortgages_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(parties_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(rent_payments_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(option_exercises_bp)
    app.register_blueprint(mortgages_bp)
    app.register_blueprint(clock_bp)

    # Serialize every request through the global store lock so multi-step
    # mutations (transitions + cascades) are atomic relative to one another.
    @app.before_request
    def _acquire_lock():
        db.LOCK.acquire()
        g._lock_held = True

    @app.teardown_request
    def _release_lock(exc):
        if getattr(g, "_lock_held", False):
            db.LOCK.release()
            g._lock_held = False

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        # Unknown route -> use the catalog not-found shape.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
