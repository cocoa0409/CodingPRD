"""Process entry point for the New-Home Structural Warranty Insurance API.

Every boot is a clean slate: `db` holds plain Python dicts that start empty,
nothing is read from or written to disk, and no entity data of any kind is
seeded.  Re-invoking start.sh therefore wipes every byte of state.
"""

import os
import sys
import traceback
from datetime import date, datetime
from decimal import Decimal

from flask import Flask

import db
import response
from errors import ApiError
from routes import (builders, claims, escalations, ledger, parties, policies,
                    transfers)

BLUEPRINTS = (builders.bp, parties.bp, policies.bp, transfers.bp, claims.bp,
              ledger.bp, escalations.bp)


def _json_default(obj):
    """Decimal rates serialise as JSON numbers; money is always integer cents."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return db.iso_ms(obj)
    if isinstance(obj, date):
        return "%04d-%02d-%02d" % (obj.year, obj.month, obj.day)
    raise TypeError("%r is not JSON serialisable" % (obj,))


def _install_json(app):
    try:
        from flask.json.provider import DefaultJSONProvider

        class Provider(DefaultJSONProvider):
            sort_keys = False

            @staticmethod
            def default(obj):
                return _json_default(obj)

        app.json = Provider(app)
    except ImportError:  # Flask < 2.2
        import json

        class Encoder(json.JSONEncoder):
            def default(self, obj):  # noqa: D401
                try:
                    return _json_default(obj)
                except TypeError:
                    return super().default(obj)

        app.json_encoder = Encoder


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False
    _install_json(app)

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix="/warranty")
    # The logical-clock control endpoint sits outside the /warranty prefix.
    app.register_blueprint(escalations.clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error_response("ERR_NOT_FOUND", "no such route", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.error_response(
            "ERR_METHOD_NOT_ALLOWED", "method not allowed on this route", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        traceback.print_exc(file=sys.stderr)
        return response.error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, use_reloader=False, threaded=True)
