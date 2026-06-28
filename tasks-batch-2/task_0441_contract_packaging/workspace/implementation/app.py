"""Contract Packaging / Co-Packing API — Flask entry point.

In-memory only. No seeding, no persistence. A fresh process starts with an
empty store and the logical clock at 2026-01-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError

from routes.customers import bp as customers_bp
from routes.components import bp as components_bp
from routes.recipes import bp as recipes_bp
from routes.lines import bp as lines_bp
from routes.runs import bp as runs_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Ensure a clean store on every fresh process (per-test-server isolation).
    db.reset()

    app.register_blueprint(customers_bp)
    app.register_blueprint(components_bp)
    app.register_blueprint(recipes_bp)
    app.register_blueprint(lines_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return response.error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        # Method not allowed maps to a not-found-style rejection for unknown ops.
        return response.error("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        code = err.code or 500
        if code == 400:
            return response.error("ERR_INVALID_REQUEST", "Bad request", 400)
        return response.error("ERR_INVALID_REQUEST", str(err), code if code < 500 else 500)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return response.error("ERR_INTERNAL", "Internal server error: %s" % err, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
