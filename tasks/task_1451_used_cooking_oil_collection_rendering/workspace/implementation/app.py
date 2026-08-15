"""Used Cooking Oil Collection & Rendering API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding).
Listens on 0.0.0.0:$PORT (default 10000) in the foreground.
"""

import os

from flask import Flask

from errors import ApiError, err
from response import error_response
from routes_billing import bp as billing_bp
from routes_customers import bp as customers_bp
from routes_fleet import bp as fleet_bp
from routes_ops import bp as ops_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(fleet_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(err("ERR_VALIDATION", "Malformed request: %s" % e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
