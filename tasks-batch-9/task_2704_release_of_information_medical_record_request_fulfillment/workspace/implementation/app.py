"""Release-of-Information medical record request fulfillment service.

Flask + in-memory dicts.  Nothing is persisted and nothing is seeded: the
process starts empty on every boot and every entity arrives through the API.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_authorizations
import routes_config
import routes_deliveries
import routes_invoices
import routes_requests
import routes_reviews
import routes_segments
import routes_sweep
from envelope import error
from errors import ERRORS, ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (routes_config, routes_authorizations, routes_requests,
                   routes_segments, routes_invoices, routes_deliveries,
                   routes_reviews, routes_sweep):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        status, message = ERRORS["ERR_NOT_FOUND"]
        return error("ERR_NOT_FOUND", message, status)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        status, message = ERRORS["ERR_METHOD_NOT_ALLOWED"]
        return error("ERR_METHOD_NOT_ALLOWED", message, status)

    @app.errorhandler(400)
    def _bad_request(_exc):
        status, message = ERRORS["ERR_INVALID_REQUEST"]
        return error("ERR_INVALID_REQUEST", message, status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return error("ERR_INVALID_REQUEST", exc.description, exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error("ERR_INTERNAL", str(exc) or "Internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
