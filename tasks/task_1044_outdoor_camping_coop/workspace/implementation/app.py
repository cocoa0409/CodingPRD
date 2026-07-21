"""Outdoor & Camping Co-op API — Flask entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
import core as c

import routes_members
import routes_catalog
import routes_rentals
import routes_trips
import routes_tradeins
import routes_repairs
import routes_passes
import routes_special
import routes_purchases
import routes_dividends
import routes_clock


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        routes_members,
        routes_catalog,
        routes_rentals,
        routes_trips,
        routes_tradeins,
        routes_repairs,
        routes_passes,
        routes_special,
        routes_purchases,
        routes_dividends,
        routes_clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return c.error_response(e)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map framework errors (404 unknown route, 405, 400 bad JSON) into the
        # standard error envelope.
        code = e.code or 500
        mapping = {404: "ERR_VALIDATION", 405: "ERR_VALIDATION", 400: "ERR_VALIDATION"}
        error_id = mapping.get(code, "ERR_VALIDATION")
        return c.error_response(ApiError(error_id, code, e.description))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
