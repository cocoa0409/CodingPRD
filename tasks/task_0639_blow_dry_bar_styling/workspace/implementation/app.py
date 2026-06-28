"""Blow-Dry Bar API — entry point, error handlers, blueprint registration.

In-memory store only; no seeding at startup. Boots clean on every invocation.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.appointments import bp as appointments_bp
from routes.config import bp as config_bp
from routes.event_blocks import bp as event_blocks_bp
from routes.members import bp as members_bp
from routes.retail import bp as retail_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(event_blocks_bp)
    app.register_blueprint(retail_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
