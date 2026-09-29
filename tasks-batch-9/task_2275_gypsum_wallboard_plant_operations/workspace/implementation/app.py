"""Gypsum Wallboard Plant Operations API.

Flask application factory and process entry point. All state lives in memory in
db.Store and is discarded when the process exits: nothing is seeded, persisted
or cached on disk, so every boot starts from a completely empty store.
"""

import os
from datetime import date, datetime
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.config import bp as config_bp
from routes.freight import bp as freight_bp
from routes.maintenance import bp as maintenance_bp
from routes.material import bp as material_bp
from routes.production import bp as production_bp
from util import fmt_dt


class PlantJSONProvider(DefaultJSONProvider):
    """Decimals serialise as JSON numbers; instants as ISO 8601 UTC."""

    sort_keys = False

    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return fmt_dt(obj)
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, set):
            return sorted(obj)
        return DefaultJSONProvider.default(obj)


def create_app():
    app = Flask(__name__)
    app.json = PlantJSONProvider(app)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(material_bp)
    app.register_blueprint(production_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(freight_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "resource not found", 404)
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "method not allowed for this resource", 405
            )
        if exc.code and 400 <= exc.code < 500:
            return error_response(
                "ERR_INVALID_REQUEST", exc.description or "invalid request", exc.code
            )
        return error_response("ERR_INTERNAL", exc.description or "internal error", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
