"""Window-Tint & Vehicle-Wrap API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot. No seeding.
Reads PORT from the environment, binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError

from routes.catalog import bp as catalog_bp
from routes.vehicles_fleet import bp as vehicles_fleet_bp
from routes.exemptions import bp as exemptions_bp
from routes.bays_installers import bp as bays_installers_bp
from routes.quotes import bp as quotes_bp
from routes.work_orders import bp as work_orders_bp
from routes.wrap_proofs import bp as wrap_proofs_bp
from routes.callbacks import bp as callbacks_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(vehicles_fleet_bp)
    app.register_blueprint(exemptions_bp)
    app.register_blueprint(bays_installers_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(wrap_proofs_bp)
    app.register_blueprint(callbacks_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> treat as not found in our envelope.
        return response.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Map any other werkzeug HTTP error (e.g. malformed JSON -> 400).
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "Bad request.", 400)
        return response.error("ERR_INVALID_REQUEST", str(exc), exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INVALID_REQUEST", "Unexpected error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
