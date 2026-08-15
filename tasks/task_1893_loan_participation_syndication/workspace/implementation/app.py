"""Loan Participation & Syndication Administration API — entry point."""
import os

from flask import Flask

import errors
from responses import (
    error_response,
    not_found_handler,
    method_not_allowed_handler,
)

import routes_core
import routes_funding
import routes_payments
import routes_mods
import routes_defaults
import routes_reporting
import routes_transfers


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        routes_core.bp,
        routes_funding.bp,
        routes_payments.bp,
        routes_mods.bp,
        routes_defaults.bp,
        routes_reporting.bp,
        routes_transfers.bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err)

    app.register_error_handler(404, not_found_handler)
    app.register_error_handler(405, method_not_allowed_handler)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(errors.ApiError("ERR_INVALID_REQUEST", str(err), 400))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
