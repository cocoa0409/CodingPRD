"""Entry point: app factory, error handlers, blueprint registration.

In-memory only (db.py). No seeding at startup — the store is empty on every
boot. Binds 0.0.0.0:$PORT (default 10000), foreground.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.fleet import bp as fleet_bp
from routes.move_jobs import bp as move_jobs_bp
from routes.surveys import bp as surveys_bp
from routes.packing_orders import bp as packing_orders_bp
from routes.estimates import bp as estimates_bp
from routes.dispatches import bp as dispatches_bp
from routes.storage_lots import bp as storage_lots_bp
from routes.damage_claims import bp as damage_claims_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(fleet_bp)
    app.register_blueprint(move_jobs_bp)
    app.register_blueprint(surveys_bp)
    app.register_blueprint(packing_orders_bp)
    app.register_blueprint(estimates_bp)
    app.register_blueprint(dispatches_bp)
    app.register_blueprint(storage_lots_bp)
    app.register_blueprint(damage_claims_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> ERR_NOT_FOUND (PRD §5).
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(e):
        # Malformed body / bad request -> ERR_VALIDATION (PRD §3.12).
        return error_response("ERR_VALIDATION", "Malformed request.", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map any other werkzeug HTTP error into the standard envelope.
        if e.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if e.code == 405:
            return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)
        return error_response("ERR_VALIDATION", e.description or "Request error.", e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Last-resort guard; should not normally fire.
        return error_response("ERR_VALIDATION", "Unexpected error: %s" % e, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
