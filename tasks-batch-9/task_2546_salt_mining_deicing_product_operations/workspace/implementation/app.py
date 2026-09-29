"""Salt Mining and Deicing Product Operations API."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError, ERR_INVALID_REQUEST
from routes.allocations import bp as allocations_bp
from routes.batches import bp as batches_bp
from routes.clock import bp as clock_bp
from routes.contracts import bp as contracts_bp
from routes.depots import bp as depots_bp
from routes.forecasts import bp as forecasts_bp
from routes.inspections import bp as inspections_bp
from routes.lots import bp as lots_bp
from routes.mines import bp as mines_bp
from routes.orders import bp as orders_bp
from routes.panels import bp as panels_bp
from routes.runs import bp as runs_bp
from routes.shipments import bp as shipments_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in (clock_bp, mines_bp, panels_bp, inspections_bp, runs_bp,
                      batches_bp, depots_bp, lots_bp, shipments_bp,
                      forecasts_bp, contracts_bp, orders_bp, allocations_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        return response.error(ERR_INVALID_REQUEST, exc.description or "invalid request",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        return response.error("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
