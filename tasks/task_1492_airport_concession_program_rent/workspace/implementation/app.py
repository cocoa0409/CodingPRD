"""Airport Concession Rent API — Flask entry point.

Mounts every route group, installs the authentication hook and the standard
error-envelope handlers, and serves on 0.0.0.0:$PORT (default 10000).
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import authenticate
from response import err
from routes import tenants, leases, sales_reports, settlements, audits, reviews
from routes import draws, violations, waivers, enplanements, clock


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _authenticate():
        authenticate()

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return err(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def _handle_404(e):
        return err(ERR_NOT_FOUND, 404, 'The requested resource was not found')

    @app.errorhandler(405)
    def _handle_405(e):
        return err(ERR_INVALID_REQUEST, 405, 'Method not allowed for this path')

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        return err('ERR_INTERNAL', 500, 'Internal server error')

    for module in (tenants, leases, sales_reports, settlements, audits, reviews,
                   draws, violations, waivers, enplanements, clock):
        app.register_blueprint(module.bp)

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
