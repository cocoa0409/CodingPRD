"""Flask app entry point: error handlers, reconcile hook, route registration."""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response
from services.core import reconcile_all


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _reconcile():
        # Lazy clock-driven transitions on every access (PRD §2.4)
        reconcile_all()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _nf(e):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def _mna(e):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response(ERR_INVALID_REQUEST, str(e), 400)

    from routes.zones import bp as zones_bp
    from routes.households import bp as households_bp
    from routes.subscriptions import bp as subscriptions_bp
    from routes.carts import bp as carts_bp
    from routes.routes import bp as routes_bp
    from routes.tickets import bp as tickets_bp
    from routes.inspections import bp as inspections_bp
    from routes.surge import bp as surge_bp
    from routes.facilities import bp as facilities_bp
    from routes.compost import bp as compost_bp
    from routes.credits import bp as credits_bp
    from routes.campaigns import bp as campaigns_bp
    from routes.clock import bp as clock_bp

    for bp in (zones_bp, households_bp, subscriptions_bp, carts_bp, routes_bp,
               tickets_bp, inspections_bp, surge_bp, facilities_bp, compost_bp,
               credits_bp, campaigns_bp, clock_bp):
        app.register_blueprint(bp)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
