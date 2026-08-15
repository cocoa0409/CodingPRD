"""Anti-Bribery & Third-Party Due Diligence API — Flask entry point.

Mounts all routes under /compliance. The store is fully in-memory and starts
empty on every boot (no seeding); the logical clock starts at 2026-05-01T00:00:00Z.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
import routes.config as config_routes
import routes.third_parties as tp_routes
import routes.contracts as contract_routes
import routes.operations as ops_routes


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(config_routes.bp)
    app.register_blueprint(tp_routes.bp)
    app.register_blueprint(contract_routes.bp)
    app.register_blueprint(ops_routes.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_VALIDATION", str(err), 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
