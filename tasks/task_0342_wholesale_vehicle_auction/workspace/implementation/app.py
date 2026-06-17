"""Wholesale Vehicle Auction API entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.sales import bp as sales_bp
from routes.dealers import bp as dealers_bp
from routes.consignments import bp as consignments_bp
from routes.lots import bp as lots_bp
from routes.arbitration import bp as arbitration_bp
from routes.settlements import bp as settlements_bp
from routes.transport import bp as transport_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(sales_bp)
    app.register_blueprint(dealers_bp)
    app.register_blueprint(consignments_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(arbitration_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(transport_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route -> generic validation-style 404 envelope.
        return error_response("ERR_VALIDATION", "Not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_VALIDATION", "Method not allowed.", 405)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_VALIDATION", "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_VALIDATION", "Internal error: %s" % str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
