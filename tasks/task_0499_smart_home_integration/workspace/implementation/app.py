"""Smart Home Integration API — Flask entry point.

In-memory only; a fresh process per start.sh boot wipes all state. Nothing is
seeded at startup; tests build all state via the API.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.clients import bp as clients_bp
from routes.clock import bp as clock_bp
from routes.projects import bp as projects_bp
from routes.racks import bp as racks_bp
from routes.proposals import bp as proposals_bp
from routes.devices import bp as devices_bp
from routes.scenes import bp as scenes_bp
from routes.visits import bp as visits_bp
from routes.crew import bp as crew_bp
from routes.contracts import bp as contracts_bp
from routes.rma import bp as rma_bp
from routes.change_orders import bp as change_orders_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clients_bp)
    app.register_blueprint(clock_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(racks_bp)
    app.register_blueprint(proposals_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(scenes_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(crew_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(rma_bp)
    app.register_blueprint(change_orders_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        # Map any other werkzeug HTTP error into the standard envelope.
        code = exc.code or 500
        if code == 400:
            return error_response("ERR_INVALID_REQUEST", 422, "Malformed request")
        return error_response("ERR_INVALID_REQUEST", 422, exc.description or "Request error")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Never leak a 500 in the wrong shape; treat as invalid request.
        return error_response("ERR_INVALID_REQUEST", 422, "Unexpected error")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
