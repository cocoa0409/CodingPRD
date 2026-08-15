"""Entry point: Flask app assembly, error handlers, route registration."""

import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError  # noqa: E402
from response import error_response  # noqa: E402
from routes import (  # noqa: E402
    audits,
    claims,
    clock_routes,
    documents,
    inspections,
    milestones,
    purchase_orders,
    quotations,
    registry,
    shipments,
    sourcing_requests,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        registry,
        audits,
        documents,
        sourcing_requests,
        quotations,
        purchase_orders,
        milestones,
        inspections,
        shipments,
        claims,
        clock_routes,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(
            "ERR_VALIDATION", "Method not allowed for this path", 405
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        import traceback

        traceback.print_exc()
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
