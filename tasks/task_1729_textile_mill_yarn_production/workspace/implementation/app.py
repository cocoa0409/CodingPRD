"""Textile Mill Yarn Production API — Flask entry point.

Mounts all route blueprints under /mill, registers the error handler for the
standard error envelope, and binds 0.0.0.0:$PORT (default 10000).

The store starts EMPTY on every boot — no seeding anywhere. Every entity a
test needs is built via the declared API surface.
"""

import os

from flask import Flask

from errors import ApiError, err_not_found, err_invalid_request
from response import error_response

from routes import (
    blend_recipes,
    customer_orders,
    dye_lots,
    fiber_lots,
    finished_rolls,
    lab_dips,
    machine_assignments,
    quality_tests,
    shade_bands,
    spinning_machines,
    yarn_lots,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(fiber_lots.bp)
    app.register_blueprint(blend_recipes.bp)
    app.register_blueprint(spinning_machines.bp)
    app.register_blueprint(yarn_lots.bp)
    app.register_blueprint(machine_assignments.bp)
    app.register_blueprint(shade_bands.bp)
    app.register_blueprint(lab_dips.bp)
    app.register_blueprint(dye_lots.bp)
    app.register_blueprint(quality_tests.bp)
    app.register_blueprint(finished_rolls.bp)
    app.register_blueprint(customer_orders.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        err = err_not_found("Route not found")
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(405)
    def handle_405(exc):
        err = err_not_found("Method not allowed on this route")
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(400)
    def handle_400(exc):
        err = err_invalid_request("Malformed request")
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        return error_response("ERR_INVALID_REQUEST", 400, str(exc))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
