"""Warehouse Receipt & Commodity Collateral Administration API.

Flask application factory and process entry point.  All state lives in
process memory (see core.store); nothing is persisted and nothing is seeded,
so every fresh boot starts completely empty.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

from core import ApiError, respond_error  # noqa: E402
from routes import (agreements, bins, claims, clock, deliveries, liens, parties,
                    receipts, reports, tickets, warehouses)  # noqa: E402

BLUEPRINTS = (
    clock.bp,
    warehouses.bp,
    parties.bp,
    agreements.bp,
    bins.bp,
    tickets.bp,
    receipts.bp,
    liens.bp,
    reports.bp,
    deliveries.bp,
    claims.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return respond_error("ERR_NOT_FOUND", 404,
                                 "The requested resource does not exist.")
        if exc.code == 405:
            return respond_error("ERR_METHOD_NOT_ALLOWED", 405,
                                 "The method is not allowed for this path.")
        if exc.code in (400, 415):
            return respond_error("ERR_VALIDATION", 422,
                                 "The request body could not be parsed.")
        return respond_error("ERR_INTERNAL", exc.code or 500,
                             exc.description or "Request failed.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return respond_error("ERR_INTERNAL", 500, str(exc) or "Internal error.")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True,
            use_reloader=False)
