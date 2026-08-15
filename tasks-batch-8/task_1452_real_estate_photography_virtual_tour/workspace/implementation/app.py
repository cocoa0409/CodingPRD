"""Real Estate Media API — Flask application entry point."""

import os
from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.clock import bp as clock_bp
from routes.markets import bp as markets_bp
from routes.photographers import bp as photographers_bp
from routes.client_agents import bp as client_agents_bp
from routes.shoot_bookings import bp as shoot_bookings_bp
from routes.authorizations import bp as authorizations_bp
from routes.asset_bundles import bp as asset_bundles_bp
from routes.revisions import bp as revisions_bp
from routes.virtual_tour import bp as virtual_tour_bp
from routes.license import bp as license_bp
from routes.reschedule_events import bp as reschedule_events_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(markets_bp)
    app.register_blueprint(photographers_bp)
    app.register_blueprint(client_agents_bp)
    app.register_blueprint(shoot_bookings_bp)
    app.register_blueprint(authorizations_bp)
    app.register_blueprint(asset_bundles_bp)
    app.register_blueprint(revisions_bp)
    app.register_blueprint(virtual_tour_bp)
    app.register_blueprint(license_bp)
    app.register_blueprint(reschedule_events_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, 400, "Malformed request")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Surface unexpected errors as a 500-shaped error envelope
        return error_response("ERR_INTERNAL", 500, str(err))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
