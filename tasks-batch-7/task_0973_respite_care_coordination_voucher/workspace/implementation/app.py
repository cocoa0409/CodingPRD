"""Flask app entry point. Registers blueprints and error handlers."""
import os
from flask import Flask

from errors import ApiError
from response import error as error_response
from routes import programs, caregivers, allocations, vouchers, providers, bookings, visits, claims, emergency


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(programs.bp)
    app.register_blueprint(caregivers.bp)
    app.register_blueprint(allocations.bp)
    app.register_blueprint(vouchers.bp)
    app.register_blueprint(providers.bp)
    app.register_blueprint(bookings.bp)
    app.register_blueprint(visits.bp)
    app.register_blueprint(claims.bp)
    app.register_blueprint(emergency.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_INVALID_REQUEST", 404, "Not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_generic(e):
        # last-resort: surface as invalid request to keep envelope shape
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 400, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
