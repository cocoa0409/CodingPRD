import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.clock_routes import clock_bp
from routes.marinas import marinas_bp
from routes.forklifts import forklifts_bp
from routes.racks import racks_bp
from routes.owners import owners_bp
from routes.vessels import vessels_bp
from routes.insurance import insurance_bp
from routes.agreements import agreements_bp
from routes.waitlist import waitlist_bp
from routes.launches import launches_bp
from routes.slots import slots_bp
from routes.service_orders import service_orders_bp
from routes.invoices import invoices_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(marinas_bp)
    app.register_blueprint(forklifts_bp)
    app.register_blueprint(racks_bp)
    app.register_blueprint(owners_bp)
    app.register_blueprint(vessels_bp)
    app.register_blueprint(insurance_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(waitlist_bp)
    app.register_blueprint(launches_bp)
    app.register_blueprint(slots_bp)
    app.register_blueprint(service_orders_bp)
    app.register_blueprint(invoices_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        # Unknown method on a known path maps to not-found semantics.
        return error_response(ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(ERR_INVALID_REQUEST, "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
