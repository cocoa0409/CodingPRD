"""Lab Reagent Cold Chain API — Flask entry point."""
import os

from flask import Flask

from .errors import ApiError
from .response import err
from . import routes_core, routes_orders, routes_shipments, routes_recurring
from . import routes_quality


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return err('ERR_NOT_FOUND', 'The requested path does not exist', 404)

    @app.errorhandler(405)
    def handle_405(e):
        return err('ERR_METHOD_NOT_ALLOWED',
                   'Method not allowed on this path', 405)

    @app.errorhandler(500)
    def handle_500(e):
        return err('ERR_INTERNAL', 'Internal server error', 500)

    for module in (routes_core, routes_orders, routes_shipments,
                   routes_recurring, routes_quality):
        app.register_blueprint(module.bp, url_prefix='/lab')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
