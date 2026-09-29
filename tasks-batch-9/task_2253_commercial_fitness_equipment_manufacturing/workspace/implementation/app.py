"""Commercial Fitness Equipment Manufacturing API — Flask reference implementation.

Storage is in-memory only and starts completely empty on every boot: no seeding,
no preloading, no persistence of any kind.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ERROR_STATUS, ApiError
from store import clear_mutation_state, store

from routes.assets import bp as assets_bp
from routes.catalogue import bp as catalogue_bp
from routes.clock import bp as clock_bp
from routes.facilities import bp as facilities_bp
from routes.firmware import bp as firmware_bp
from routes.installs import bp as installs_bp
from routes.maintenance import bp as maintenance_bp
from routes.orders import bp as orders_bp
from routes.partners import bp as partners_bp
from routes.testing import bp as testing_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in (
        catalogue_bp,
        testing_bp,
        firmware_bp,
        facilities_bp,
        orders_bp,
        partners_bp,
        installs_bp,
        assets_bp,
        maintenance_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _open_transaction():
        clear_mutation_state()
        g.snapshot = store.snapshot()

    def _rollback():
        snap = g.pop("snapshot", None)
        if snap is not None:
            store.restore(snap)
        clear_mutation_state()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        _rollback()
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        _rollback()
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return error(
                "ERR_METHOD_NOT_ALLOWED",
                "The method is not allowed for this resource.",
                405,
            )
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error(
            "ERR_INTERNAL",
            exc.description or "Unexpected error.",
            exc.code or ERROR_STATUS["ERR_INTERNAL"],
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        _rollback()
        return error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
