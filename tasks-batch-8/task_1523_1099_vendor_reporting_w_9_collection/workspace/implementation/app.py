import os

from flask import Flask

from errors import ApiError
from response import error_envelope

import routes_clock
import routes_tax_years
import routes_vendors
import routes_w9
import routes_payments
import routes_withholding
import routes_remittances
import routes_returns
import routes_transmittals
import routes_state
import routes_bnotices
import routes_merges


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for mod in (routes_clock, routes_tax_years, routes_vendors, routes_w9,
                routes_payments, routes_withholding, routes_remittances,
                routes_returns, routes_transmittals, routes_state,
                routes_bnotices, routes_merges):
        mod.register(app)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_envelope(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return error_envelope("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_envelope("ERR_NOT_FOUND", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, ApiError):
            return error_envelope(e.error_id, e.status, e.message)
        return error_envelope("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
