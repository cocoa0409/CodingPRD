"""Micromobility Scooter Share API — Flask entry point.

In-memory only: all state lives in db.py module-level dicts and is wiped on each
process boot (start.sh re-invocation). No entity is seeded, preloaded, or
hardcoded at startup; every entity any test needs is built via the declared API.
"""
import os

from flask import Flask

import errors
from response import error as error_response
from routes.plans import bp as plans_bp
from routes.zones import bp as zones_bp
from routes.vehicles import bp as vehicles_bp
from routes.riders import bp as riders_bp
from routes.wallet_transactions import bp as wallet_transactions_bp
from routes.low_income import bp as low_income_bp
from routes.trips import bp as trips_bp
from routes.trip_segments import bp as trip_segments_bp
from routes.technicians import bp as technicians_bp
from routes.rebalancing_tasks import bp as rebalancing_tasks_bp
from routes.fines import bp as fines_bp
from routes.mds_reports import bp as mds_reports_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        plans_bp, zones_bp, vehicles_bp, riders_bp, wallet_transactions_bp,
        low_income_bp, trips_bp, trip_segments_bp, technicians_bp,
        rebalancing_tasks_bp, fines_bp, mds_reports_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        # Unknown method on a known path -> not-found envelope.
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        # Surface unexpected failures as a well-formed invalid-request envelope.
        return error_response(errors.ERR_INVALID_REQUEST, str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Build Werkzeug's server directly so we can enlarge the listen backlog.
    # Under the 8x-concurrent per-test-server sweep the default backlog can be
    # exhausted between the runner's readiness probe and the test's first
    # request, surfacing as a transport-level connection reset. A larger
    # request_queue_size keeps queued connections from being dropped.
    from werkzeug.serving import make_server

    httpd = make_server("0.0.0.0", port, app, threaded=True)
    httpd.request_queue_size = 128
    httpd.socket.listen(128)
    httpd.serve_forever()
