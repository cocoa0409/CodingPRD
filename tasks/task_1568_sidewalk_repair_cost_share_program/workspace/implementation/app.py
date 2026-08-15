"""Sidewalk Repair & Cost-Share Program API — Flask entry point."""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config['JSON_SORT_KEYS'] = False

    import routes_cycles
    import routes_inventory
    import routes_notices
    import routes_applications
    import routes_bidding
    import routes_forestry
    import routes_liens
    import routes_misc

    for mod in (routes_cycles, routes_inventory, routes_notices,
                routes_applications, routes_bidding, routes_forestry,
                routes_liens, routes_misc):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response('ERR_NOT_FOUND', 'Route not found', 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response('ERR_METHOD_NOT_ALLOWED', 'Method not allowed', 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response('ERR_INTERNAL', str(e), 500)

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)
