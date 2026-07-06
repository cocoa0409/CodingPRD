"""Podcast Production & Editing API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No seeding.
Registers all route blueprints and the global error handlers.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.clock_routes import bp as clock_bp
from routes.shows import bp as shows_bp
from routes.contracts import bp as contracts_bp
from routes.retainer_cycles import bp as retainer_cycles_bp
from routes.engineers import bp as engineers_bp
from routes.episodes import bp as episodes_bp
from routes.sessions import bp as sessions_bp
from routes.deliverables import bp as deliverables_bp
from routes.invoices import bp as invoices_bp
from routes.ad_campaigns import bp as ad_campaigns_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        shows_bp,
        contracts_bp,
        retainer_cycles_bp,
        engineers_bp,
        episodes_bp,
        sessions_bp,
        deliverables_bp,
        invoices_bp,
        ad_campaigns_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — surface as ERR_NOT_FOUND in the standard envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
