"""Entry point: error handlers and route registration (PRD §2)."""
import os

from flask import Flask, request

from errors import ApiError
from response import error_response

from routes.brokerages import bp as brokerages_bp
from routes.properties import bp as properties_bp
from routes.listings import bp as listings_bp
from routes.requirements import bp as requirements_bp
from routes.tours import bp as tours_bp
from routes.deals import bp as deals_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(brokerages_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(requirements_bp)
    app.register_blueprint(tours_bp)
    app.register_blueprint(deals_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION", 400, "Malformed request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_VALIDATION", 400, "Unexpected error: %s" % str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
