"""Dairy Digester RNG API -- Flask application factory and entry point.

Storage is entirely in-memory and starts empty on every boot: no fixture, seed
or preloaded row exists anywhere in this package.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes import (admin, agreements, applications, audits, batches, dairies,
                    deliveries, facilities, interconnects, nominations, ops_days,
                    pathways, statements)

BLUEPRINTS = (
    admin.bp,
    dairies.bp,
    facilities.bp,
    agreements.bp,
    deliveries.bp,
    ops_days.bp,
    interconnects.bp,
    nominations.bp,
    pathways.bp,
    batches.bp,
    audits.bp,
    applications.bp,
    statements.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return error("ERR_METHOD_NOT_ALLOWED",
                         "The method is not allowed for this resource.", 405)
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error("ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", exc)
        return error("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
