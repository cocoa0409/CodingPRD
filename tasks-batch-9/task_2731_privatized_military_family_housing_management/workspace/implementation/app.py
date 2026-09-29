"""Privatized Military Family Housing Management API — Flask entry point.

Storage is entirely in-memory: every dict lives in `db.Store` and dies with the
process. Nothing is seeded at startup; all state arrives through API calls.
"""

import os
from decimal import Decimal

from flask import Flask, jsonify

import db as store
import response as resp
from errors import ApiError
from routes import (accounts, disputes, hazards, inspections, installations,
                    leases, members, system, units, waitlist, work_orders)

BLUEPRINTS = (
    system.bp,
    installations.bp,
    units.bp,
    members.bp,
    waitlist.bp,
    leases.bp,
    inspections.bp,
    work_orders.bp,
    hazards.bp,
    disputes.bp,
    accounts.bp,
)


class _JSONProvider(Flask.json_provider_class):
    """Serialise Decimal as a JSON number so money/percent fields stay exact."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.json = _JSONProvider(app)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin():
        store.begin_request()

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return resp.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(_exc):
        return resp.error("ERR_INVALID_REQUEST", "The request body is not valid JSON.", 400)

    @app.errorhandler(404)
    def _not_found(_exc):
        return resp.error("ERR_INVALID_REQUEST", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return resp.error("ERR_INVALID_REQUEST",
                          "The method is not allowed for this resource.", 405)

    @app.errorhandler(415)
    def _unsupported(_exc):
        return resp.error("ERR_INVALID_REQUEST",
                          "The request body must be JSON.", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return resp.error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return resp.error("ERR_INTERNAL", "An unexpected server error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
