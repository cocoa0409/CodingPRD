"""Check Adjustment & Return Item Processing API — Flask entry point.

Boots with an empty store and the logical clock fixed at 2026-05-01T00:00:00Z.
Listens on 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

import routes_accounts
import routes_banks
import routes_items
import routes_holds
import routes_cases
import routes_claims
import routes_warranties
import routes_notifications
import routes_fees
import routes_recredits
import routes_ledger
import routes_ops


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (routes_accounts, routes_banks, routes_items, routes_holds,
                   routes_cases, routes_claims, routes_warranties,
                   routes_notifications, routes_fees, routes_recredits,
                   routes_ledger, routes_ops):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        status = err.code if err.code in (400, 401, 403, 404, 405) else 404
        return error_response('ERR_NOT_FOUND', status,
                              err.description or 'Not found')

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response('ERR_INTERNAL', 500, 'Internal server error')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
