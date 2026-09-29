"""Retail Energy Refrigeration Ops API — application entry point.

Storage is in-memory only and nothing is ever seeded: every entity in the
system is created through the declared endpoints.
"""

import os

from flask import Flask

import envelope
import routes_accounts
import routes_bills
import routes_cases
import routes_dr
import routes_excursions
import routes_faults
import routes_misc
import routes_overrides
import routes_retrofits
import routes_standards
import routes_stores
from errors import ApiError

PREFIX = "/energy-ops"

BLUEPRINTS = (
    routes_stores.bp,
    routes_standards.bp,
    routes_accounts.bp,
    routes_bills.bp,
    routes_dr.bp,
    routes_cases.bp,
    routes_excursions.bp,
    routes_overrides.bp,
    routes_faults.bp,
    routes_retrofits.bp,
    routes_misc.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return envelope.error_response(error.error_id, error.message,
                                       error.http_status)

    @app.errorhandler(404)
    def handle_not_found(error):
        return envelope.error_response("ERR_NOT_FOUND",
                                       "no such resource path", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return envelope.error_response("ERR_METHOD_NOT_ALLOWED",
                                       "method not allowed for this path", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return handle_api_error(error)
        return envelope.error_response("ERR_INTERNAL",
                                       "unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
