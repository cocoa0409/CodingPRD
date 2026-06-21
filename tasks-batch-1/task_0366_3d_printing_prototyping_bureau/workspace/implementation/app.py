"""Printing Bureau API — Flask entry point.

Boots cleanly with an empty in-memory store on every process start. No seeding.
Listens on 0.0.0.0:$PORT (default 10000), foreground.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.catalogue import bp as catalogue_bp
from routes.print_files import bp as print_files_bp
from routes.orders import bp as orders_bp
from routes.finishing_tasks import bp as finishing_tasks_bp
from routes.print_runs import bp as print_runs_bp
from routes.shipments import bp as shipments_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalogue_bp)
    app.register_blueprint(print_files_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(finishing_tasks_bp)
    app.register_blueprint(print_runs_bp)
    app.register_blueprint(shipments_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_err):
        # Unknown route -> not found, in the standard envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Defensive: never leak a 500 in a non-enveloped form. Map unknown
        # failures to a generic invalid-request so the envelope is consistent.
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % err, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
