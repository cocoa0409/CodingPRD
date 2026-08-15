"""Joint Trench Undergrounding API — Flask entry point.

In-memory only; the store starts empty on every boot and nothing is seeded.
The logical clock starts at exactly 2026-08-01T00:00:00Z.
"""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.projects import bp as projects_bp
from routes.participations import bp as participations_bp
from routes.segments import bp as segments_bp
from routes.slots import bp as slots_bp
from routes.rightofway import parcels_bp, easements_bp, permits_bp
from routes.conversions import bp as conversions_bp
from routes.outages import bp as outages_bp
from routes.change_orders import bp as change_orders_bp
from routes.costs import bp as costs_bp
from routes.trueups import bp as trueups_bp
from routes.invoices import bp as invoices_bp
from routes.restoration import bp as restoration_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in (
        projects_bp,
        participations_bp,
        segments_bp,
        slots_bp,
        parcels_bp,
        easements_bp,
        permits_bp,
        conversions_bp,
        outages_bp,
        change_orders_bp,
        costs_bp,
        trueups_bp,
        invoices_bp,
        restoration_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
