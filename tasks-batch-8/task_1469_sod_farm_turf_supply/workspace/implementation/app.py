"""Sod Farm & Turf Supply API — Flask entry point.

In-memory only: all state lives in process-local dicts (db.py). No seeding,
no disk persistence. Boots cleanly from a fresh process on every invocation.
"""
import os

from flask import Flask
from werkzeug.exceptions import BadRequest, MethodNotAllowed, NotFound

from errors import ApiError, err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from util import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.configs import bp as configs_bp
    from routes.customers import bp as customers_bp
    from routes.crews import bp as crews_bp
    from routes.fields import bp as fields_bp
    from routes.harvest import bp as harvest_bp
    from routes.quotes import bp as quotes_bp
    from routes.orders import bp as orders_bp
    from routes.referrals import bp as referrals_bp
    from routes.warranty import bp as warranty_bp
    from routes.fleet import bp as fleet_bp

    for blueprint in (configs_bp, customers_bp, crews_bp, fields_bp, harvest_bp,
                      quotes_bp, orders_bp, referrals_bp, warranty_bp, fleet_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(NotFound)
    def handle_not_found(e):
        return error_response(err(ERR_NOT_FOUND, "resource not found"))

    @app.errorhandler(MethodNotAllowed)
    def handle_method_not_allowed(e):
        return error_response(err(ERR_NOT_FOUND, "method not allowed on this path"))

    @app.errorhandler(BadRequest)
    def handle_bad_request(e):
        return error_response(err(ERR_INVALID_REQUEST, "malformed request"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(err(ERR_INVALID_REQUEST, str(e)[:200]))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
