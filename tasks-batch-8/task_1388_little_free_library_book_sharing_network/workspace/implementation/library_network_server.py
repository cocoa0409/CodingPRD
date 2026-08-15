"""Little Free Library Network API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.stewards import bp as stewards_bp
from routes.training import bp as training_bp
from routes.boxes import bp as boxes_bp
from routes.items import bp as items_bp
from routes.maintenance import bp as maintenance_bp
from routes.complaints import bp as complaints_bp
from routes.schools import bp as schools_bp
from routes.drives import bp as drives_bp
from routes.batches import bp as batches_bp
from routes.runs import bp as runs_bp
from routes.allocations import bp as allocations_bp
from routes.ops import bp as ops_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(stewards_bp)
    app.register_blueprint(training_bp)
    app.register_blueprint(boxes_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(complaints_bp)
    app.register_blueprint(schools_bp)
    app.register_blueprint(drives_bp)
    app.register_blueprint(batches_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(allocations_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
