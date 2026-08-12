"""Returns Concierge API — Flask entry point.

Mounts all resource blueprints under /v1, installs the standard error
envelope handlers, and runs the development server on $PORT (0.0.0.0).
Storage is in-memory only and starts empty on every boot.
"""

import os

from flask import Flask

from errors import ApiError
from util import error_response
import routes.orgs as orgs
import routes.shoppers as shoppers
import routes.locations as locations
import routes.orders as orders
import routes.reservations as reservations
import routes.pickups as pickups
import routes.freight as freight
import routes.exceptions as exceptions
import routes.admin as admin


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (orgs, shoppers, locations, orders, reservations,
                   pickups, freight, exceptions, admin):
        app.register_blueprint(module.bp, url_prefix="/v1")

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_):
        return error_response(ApiError("ERR_NOT_FOUND", 404,
                                       "Referenced resource does not exist"))

    @app.errorhandler(405)
    def _method_not_allowed(_):
        return error_response(ApiError("ERR_INVALID_REQUEST", 405,
                                       "Method not allowed"))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unhandled error")
        return error_response(ApiError("ERR_INVALID_REQUEST", 500, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
