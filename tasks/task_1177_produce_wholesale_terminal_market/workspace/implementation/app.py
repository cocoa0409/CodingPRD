"""Produce Terminal Market API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot;
the logical clock starts at exactly 2026-05-01T00:00:00Z.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.parties import bp as parties_bp
from routes.lots import bp as lots_bp
from routes.ripening import bp as ripening_bp
from routes.shrink import bp as shrink_bp
from routes.orders import bp as orders_bp
from routes.billing import bp as billing_bp
from routes.ops import bp as ops_bp


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    for bp in (parties_bp, lots_bp, ripening_bp, shrink_bp, orders_bp, billing_bp, ops_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a bare 500 HTML page; respond in the error envelope.
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_VALIDATION", str(err), 422)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
