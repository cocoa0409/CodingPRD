"""Flask entry point: JSON provider, request serialization, error envelope,
blueprint registration. Reads $PORT (default 10000) and binds 0.0.0.0.
"""

import os
from decimal import Decimal

from flask import Flask, g
from flask.json.provider import DefaultJSONProvider

from db import store
from errors import ApiError, not_found, invalid_request
from response import error_response


class DecimalJSONProvider(DefaultJSONProvider):
    """Serialize Decimal as a JSON number (all Decimals are pre-rounded to
    their declared precision, so float conversion is exact for output)."""

    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def create_app():
    app = Flask(__name__)
    app.json = DecimalJSONProvider(app)

    # Serialize all requests through one lock: a single call may cascade
    # across many resources (QC fail -> bundles -> entries), and the
    # consistency model is immediate.
    @app.before_request
    def _acquire_lock():
        store.lock.acquire()
        g._lock_held = True

    @app.teardown_request
    def _release_lock(exc):
        if getattr(g, "_lock_held", False):
            store.lock.release()
            g._lock_held = False

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def _handle_404(err):
        e = not_found("resource not found")
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(405)
    def _handle_405(err):
        e = invalid_request("method not allowed")
        return error_response(e.error_id, 405, e.message)

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.http_status, err.message)
        return error_response("ERR_INTERNAL", 500, str(err))

    from routes import (
        styles, tech_packs, operation_specs, trim, fabric_rolls,
        production_orders, markers, bundles, sewing, piece_work, payroll,
        quality_audits,
    )
    for module in (
        styles, tech_packs, operation_specs, trim, fabric_rolls,
        production_orders, markers, bundles, sewing, piece_work, payroll,
        quality_audits,
    ):
        app.register_blueprint(module.bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
