"""Flask entry point: error handling, route registration."""
import os
from flask import Flask
from errors import AppError, HTTP_STATUS, ERR_VALIDATION
from envelope import error as err_response

from routes.shops import bp as shops_bp
from routes.shipping_profiles import bp as sp_bp
from routes.materials import bp as materials_bp
from routes.listings import bp as listings_bp
from routes.vacation_periods import bp as vp_bp
from routes.orders import bp as orders_bp
from routes.reviews import bp as reviews_bp
from routes.cases import bp as cases_bp
from routes.payouts import bp as payouts_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(shops_bp)
    app.register_blueprint(sp_bp)
    app.register_blueprint(materials_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(vp_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(AppError)
    def handle_app_error(e):
        return err_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Route-not-found: not a spec'd resource error; return a generic 404 envelope.
        return err_response("ERR_NOT_FOUND", "route not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return err_response("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(e):
        return err_response(ERR_VALIDATION, "bad request", 400)

    @app.errorhandler(500)
    def handle_500(e):
        return err_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
