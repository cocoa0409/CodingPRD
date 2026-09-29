"""Medicare cost report preparation and wage index API.

A single Flask process holding every entity in memory. Nothing is seeded and
nothing is persisted, so a fresh boot always starts from an empty store.
"""

import os
import sys
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import response  # noqa: E402
from errors import ApiError  # noqa: E402
from routes import BLUEPRINTS  # noqa: E402


class DomainJSONProvider(DefaultJSONProvider):
    """Fixed-scale Decimals are emitted as JSON numbers, never as strings."""

    sort_keys = False

    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return DefaultJSONProvider.default(self, o)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.json = DomainJSONProvider(app)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.fail(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            return response.fail("ERR_NOT_FOUND", "No such route.", 404)
        if status == 405:
            return response.fail("ERR_METHOD_NOT_ALLOWED",
                                 "The method is not allowed for this route.", 405)
        if status == 400:
            return response.fail("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return response.fail("ERR_INTERNAL", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error: %s", exc)
        return response.fail("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
