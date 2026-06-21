"""Equestrian Barn API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot. No entity is seeded,
preloaded, or hardcoded at startup. The per-test-server isolation re-invokes
start.sh and a fresh process wipes all state.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response
from middleware import get_caller  # noqa: F401  (imported for side-effect clarity)

# Blueprints
from routes.owners import bp as owners_bp
from routes.stalls import bp as stalls_bp
from routes.horses import bp as horses_bp
from routes.boarding_agreements import bp as agreements_bp
from routes.lessons import bp as lessons_bp
from routes.service_visits import bp as visits_bp
from routes.show_entries import bp as entries_bp
from routes.turnouts import bp as turnouts_bp
from routes.invoices import bp as invoices_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(owners_bp)
    app.register_blueprint(stalls_bp)
    app.register_blueprint(horses_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(lessons_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(turnouts_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # unknown route -> generic not-found in the standard envelope
        return error_response("ERR_OWNER_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", 422, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_INVALID_REQUEST", e.code or 422, str(e))
        return error_response("ERR_INVALID_REQUEST", 422, "Internal error: %s" % e)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
