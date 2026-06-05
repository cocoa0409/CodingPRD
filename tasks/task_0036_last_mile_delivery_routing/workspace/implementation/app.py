import os

from flask import Flask

import errors
from errors import ApiError
from response import error_response

from routes.transit_centers import bp as transit_centers_bp
from routes.drivers import bp as drivers_bp
from routes.parcels import bp as parcels_bp
from routes.delivery_routes import bp as routes_bp
from routes.stops import bp as stops_bp
from routes.appointments import bp as appointments_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(transit_centers_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(parcels_bp)
    app.register_blueprint(routes_bp)
    app.register_blueprint(stops_bp)
    app.register_blueprint(appointments_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errors.ERR_INSUFFICIENT_PERMISSIONS, 403, "Method not allowed.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INTERNAL", 500, "Internal server error.")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
