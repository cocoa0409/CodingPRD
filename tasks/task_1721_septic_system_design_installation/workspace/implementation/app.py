"""Septic System Contracting API — Flask entry point.

Mounts /septic-ops. In-memory store only; starts empty on every boot.
"""

import os

from flask import Flask

import errors
import response as R
import routes_companies
import routes_contracts
import routes_customers_sites
import routes_designs
import routes_flat
import routes_installations
import routes_permits
import routes_repairs
import routes_science
import routes_variances


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return R.respond_error(err)

    @app.errorhandler(404)
    def handle_404(_err):
        return R.respond_error(errors.ApiError(
            errors.ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(_err):
        return R.respond_error(errors.ApiError(
            errors.ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(500)
    def handle_500(_err):
        return R.respond_error(errors.ApiError(
            errors.ERR_INVALID_REQUEST, 500, "Internal server error"))

    routes_companies.register(app)
    routes_customers_sites.register(app)
    routes_science.register(app)
    routes_designs.register(app)
    routes_permits.register(app)
    routes_installations.register(app)
    routes_variances.register(app)
    routes_contracts.register(app)
    routes_repairs.register(app)
    routes_flat.register(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
