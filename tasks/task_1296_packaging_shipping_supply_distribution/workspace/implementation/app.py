"""Entry point: app factory, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError, err_not_found
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.clock import bp as clock_bp
    from routes.accounts import bp as accounts_bp
    from routes.products import bp as products_bp
    from routes.warehouses import bp as warehouses_bp
    from routes.inventory import bp as inventory_bp
    from routes.orders import bp as orders_bp
    from routes.print_jobs import bp as jobs_bp
    from routes.returns import bp as returns_bp
    from routes.notifications import bp as notifications_bp

    for bp in (clock_bp, accounts_bp, products_bp, warehouses_bp, inventory_bp,
               orders_bp, jobs_bp, returns_bp, notifications_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(err_not_found())

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(err_not_found())

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        import traceback
        traceback.print_exc()
        return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    # Quiet per-request werkzeug logging: under the concurrent stability sweep
    # the per-boot stderr volume is pure I/O contention; errors still surface.
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
