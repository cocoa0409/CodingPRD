"""Convenience-Store Redistribution & DSD Wholesale API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding). The logical
clock starts at exactly 2026-05-01T00:00:00Z.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import err_response


def create_app():
    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False

    from routes_retailers import bp as retailers_bp
    from routes_catalog import bp as catalog_bp
    from routes_supply import bp as supply_bp
    from routes_manifests import bp as manifests_bp
    from routes_orders import bp as orders_bp
    from routes_billing import bp as billing_bp
    from routes_requests import bp as requests_bp

    app.register_blueprint(retailers_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(supply_bp)
    app.register_blueprint(manifests_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(requests_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return err_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return err_response(ERR_NOT_FOUND, 404, 'resource not found')

    @app.errorhandler(405)
    def handle_405(err):
        return err_response(ERR_NOT_FOUND, 404, 'resource not found')

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return err_response(err.error_id, err.http_status, err.message)
        return err_response(ERR_VALIDATION, 400, 'unprocessable request: %s' % err)

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)
