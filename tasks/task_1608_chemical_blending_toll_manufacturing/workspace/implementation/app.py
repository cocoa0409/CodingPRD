"""Entry point: Flask app, error handlers, route registration."""
import os
from flask import Flask

import errors
from response import error_response

# Blueprints
from routes.clock import bp as clock_bp
from routes.customers import bp as customers_bp
from routes.pricing_agreements import bp as pricing_agreements_bp
from routes.raw_material_lots import bp as lots_bp
from routes.recipes import bp as recipes_bp
from routes.tanks import bp as tanks_bp
from routes.cleaning_records import bp as cleaning_bp
from routes.batch_jobs import bp as batch_jobs_bp
from routes.sds import bp as sds_bp
from routes.package_shipment import bp as pkg_ship_bp
from routes.heel_disposals import bp as heel_bp
from routes.top_level import bp as top_bp


def create_app():
    app = Flask(__name__)

    # Register blueprints
    app.register_blueprint(clock_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(pricing_agreements_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(recipes_bp)
    app.register_blueprint(tanks_bp)
    app.register_blueprint(cleaning_bp)
    app.register_blueprint(batch_jobs_bp)
    app.register_blueprint(sds_bp)
    app.register_blueprint(pkg_ship_bp)
    app.register_blueprint(heel_bp)
    app.register_blueprint(top_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.not_found("not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errors.not_found("method not allowed"))

    @app.errorhandler(Exception)
    def handle_generic(e):
        import traceback
        traceback.print_exc()
        api_err = errors.ApiError(errors.ERR_INVALID_REQUEST, 400, f"internal error: {e}")
        return error_response(api_err)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
