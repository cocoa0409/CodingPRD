"""Application factory for Mobile Home Lease API."""
from flask import Flask

from .errors import ApiError, register_error_handlers
from .responses import register_request_hooks
from .routes.clock import bp as clock_bp
from .routes.conversions import bp as conversions_bp
from .routes.evictions import bp as evictions_bp
from .routes.home_sale_transfers import bp as home_sale_bp
from .routes.homes import bp as homes_bp
from .routes.leases import bp as leases_bp
from .routes.lots import bp as lots_bp
from .routes.parks import bp as parks_bp
from .routes.rent_notices import bp as rent_notices_bp
from .routes.residents import bp as residents_bp
from .routes.sweeps import bp as sweeps_bp
from .routes.utility_bills import bp as utility_bills_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    register_error_handlers(app)
    register_request_hooks(app)

    # Register blueprints
    app.register_blueprint(parks_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(homes_bp)
    app.register_blueprint(residents_bp)
    app.register_blueprint(leases_bp)
    app.register_blueprint(rent_notices_bp)
    app.register_blueprint(evictions_bp)
    app.register_blueprint(utility_bills_bp)
    app.register_blueprint(home_sale_bp)
    app.register_blueprint(conversions_bp)
    app.register_blueprint(clock_bp)
    app.register_blueprint(sweeps_bp)

    # 404 / 405 handlers using our error envelope
    @app.errorhandler(404)
    def _not_found(_e):
        from .responses import error_response
        return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        from .responses import error_response
        return error_response("ERR_RESOURCE_NOT_FOUND", "Method not allowed", 404)

    return app


__all__ = ["create_app", "ApiError"]
