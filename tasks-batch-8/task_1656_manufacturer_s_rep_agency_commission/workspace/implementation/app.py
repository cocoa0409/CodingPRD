"""Manufacturer's Rep Agency & Commission Splits API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError, err
from response import error_response


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    from routes.clock import bp as clock_bp
    from routes.principals import bp as principals_bp
    from routes.reps import bp as reps_bp
    from routes.registrations import bp as registrations_bp
    from routes.orders import bp as orders_bp
    from routes.rmas import bp as rmas_bp
    from routes.statements import bp as statements_bp
    from routes.samples import bp as samples_bp

    for bp in (clock_bp, principals_bp, reps_bp, registrations_bp, orders_bp,
               rmas_bp, statements_bp, samples_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response(ApiError("ERR_INTERNAL", 500, str(e)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
