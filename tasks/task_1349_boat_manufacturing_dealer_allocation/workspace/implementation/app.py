"""Boat Manufacturing & Dealer Allocation API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot;
the logical clock starts at exactly 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

from store import CLOCK
from util import (ApiError, respond, error_response, auth_context,
                  require_roles, json_body, need, as_datetime)
import routes_catalog
import routes_dealers
import routes_production
import routes_orders
import routes_hulls
import routes_warranty
import routes_recalls


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for mod in (routes_catalog, routes_dealers, routes_production,
                routes_orders, routes_hulls, routes_warranty, routes_recalls):
        app.register_blueprint(mod.bp)

    # ------------------------------------------------ test-driving clock
    @app.post('/_clock/set_current_utc')
    def set_clock():
        uid, role = auth_context()
        require_roles(role, 'SystemAdmin')
        data = json_body()
        instant = as_datetime(need(data, 'to_iso8601'), 'to_iso8601')
        CLOCK.set(instant)
        return respond({}, 200)

    # ------------------------------------------------ error handlers
    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.status, e.error_id, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(404, 'ERR_NOT_FOUND', 'Resource not found')

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(405, 'ERR_METHOD_NOT_ALLOWED',
                              'Method not allowed')

    @app.errorhandler(500)
    def handle_500(e):
        return error_response(500, 'ERR_INTERNAL', 'Internal server error')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
