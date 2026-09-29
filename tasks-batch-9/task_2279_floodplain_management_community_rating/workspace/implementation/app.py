"""Floodplain Management & Community Rating service — Flask application factory.

Storage is in-memory only and starts EMPTY on every boot (see db.Store).
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.certificates import bp as certificates_bp
from routes.communities import bp as communities_bp
from routes.crs import bp as crs_bp
from routes.enforcement import bp as enforcement_bp
from routes.inspections import bp as inspections_bp
from routes.ledger import bp as ledger_bp
from routes.panels import bp as panels_bp
from routes.permits import bp as permits_bp
from routes.properties import bp as properties_bp

PREFIX = "/floodplain"

_BLUEPRINTS = (
    communities_bp,
    panels_bp,
    properties_bp,
    permits_bp,
    certificates_bp,
    ledger_bp,
    inspections_bp,
    enforcement_bp,
    crs_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in _BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        mapping = {
            400: "ERR_INVALID_REQUEST",
            404: "ERR_NOT_FOUND",
            405: "ERR_METHOD_NOT_ALLOWED",
            415: "ERR_INVALID_REQUEST",
        }
        error_id = mapping.get(exc.code, "ERR_REQUEST_FAILED")
        return error_response(error_id, exc.description or error_id, exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", str(exc) or "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
