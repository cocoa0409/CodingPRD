"""Lighting & Fan Showroom API — entry point and wiring.

In-memory only. A fresh process starts with an empty store and the logical
clock at the startup default 2026-07-01T00:00:00Z. No entities are seeded.
"""
import os

from flask import Flask

from errors import ApiError
from envelope import error_body
from routes_catalog import bp as catalog_bp
from routes_orders import bp as orders_bp
from routes_workflow import bp as workflow_bp
from routes_fulfillment import bp as fulfillment_bp
from routes_returns import bp as returns_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(workflow_bp)
    app.register_blueprint(fulfillment_bp)
    app.register_blueprint(returns_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_body(e.error_id, e.message, e.http_status)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
