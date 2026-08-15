"""Consumer Complaint Management & Regulator Response API — entry point.

Binds 0.0.0.0:$PORT (default 10000). The store is in-memory only and starts
empty on every boot; the logical clock starts at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import err

import routes_admin
import routes_complaints
import routes_escalations
import routes_rcas
import routes_referrals
import routes_remediation
import routes_reviews

API_PREFIX = "/complaint-office"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (
        routes_admin,
        routes_complaints,
        routes_referrals,
        routes_rcas,
        routes_remediation,
        routes_reviews,
        routes_escalations,
    ):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def handle_404(e):
        return err(ERR_NOT_FOUND, "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return err(ERR_NOT_FOUND, "The requested resource does not exist.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err(e.error_id, e.message, e.status)
        return err("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
