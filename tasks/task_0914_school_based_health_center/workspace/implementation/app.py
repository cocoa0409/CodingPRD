"""School-Based Health Center API — Flask entry point.

The store is in-memory only and starts completely empty on every boot: no
seeding, no preloading, no fixture data of any kind.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import store
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin():
        store.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.error("ERR_RESOURCE_NOT_FOUND", "Unknown route.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return envelope.error("ERR_RESOURCE_NOT_FOUND", "Unknown route.", 404)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return envelope.error("ERR_VALIDATION", "Malformed request.", 400)
        return envelope.error("ERR_VALIDATION", exc.description or "Request failed.", exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        return envelope.error("ERR_VALIDATION", "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
