"""Inpatient Pharmacy IV Compounding API — entry point.

In-memory store, logical clock defaulting to 2026-08-01T00:00:00Z, and the
/pharmacy route surface. Boots empty; every entity is created via the API.
"""

import os

from flask import Flask

from errors import ApiError, err_not_found, err_invalid_request
from response import error
from routes_config import bp as config_bp
from routes_orders import bp as orders_bp
from routes_compounding import bp as compounding_bp
from routes_adc import bp as adc_bp
from routes_surveillance import bp as surveillance_bp
from routes_protocols import bp as protocols_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (config_bp, orders_bp, compounding_bp, adc_bp,
               surveillance_bp, protocols_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error(err_not_found())

    @app.errorhandler(405)
    def handle_405(err):
        return error(err_not_found())

    @app.errorhandler(400)
    def handle_400(err):
        return error(err_invalid_request())

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error(err)
        wrapped = ApiError("ERR_INTERNAL", 500, str(err))
        return error(wrapped)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
