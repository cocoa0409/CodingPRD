"""Air Freight Forwarding & Consolidation API — entry point.

Binds 0.0.0.0:$PORT (default 10000). The store is in-memory only and starts
empty on every boot; the logical clock starts at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

from errors import ApiError
from response import err

import routes_bookings
import routes_claims
import routes_clock
import routes_customs
import routes_hwb
import routes_mawb
import routes_rate_agreements
import routes_screening
import routes_shippers

API_PREFIX = "/air-freight"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    # The clock endpoint lives outside the business prefix (scaffold §1.5).
    app.register_blueprint(routes_clock.bp)
    for module in (
        routes_shippers,
        routes_rate_agreements,
        routes_bookings,
        routes_mawb,
        routes_hwb,
        routes_screening,
        routes_customs,
        routes_claims,
    ):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def handle_404(e):
        return err("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return err("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err(e.error_id, e.message, e.status)
        return err("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
