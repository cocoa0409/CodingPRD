"""Municipal Lien Search & Estoppel Ordering API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response

import routes_clock
import routes_reference
import routes_orders
import routes_tasks
import routes_estoppels
import routes_discrepancies
import routes_deliveries


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (
        routes_clock,
        routes_reference,
        routes_orders,
        routes_tasks,
        routes_estoppels,
        routes_discrepancies,
        routes_deliveries,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", 500, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
