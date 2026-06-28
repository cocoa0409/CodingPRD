import os

from flask import Flask, request

from errors import ApiError
from response import error_response

from routes.clock_bp import bp as clock_bp
from routes.customers import bp as customers_bp
from routes.technicians import bp as technicians_bp
from routes.routes_bp import bp as routes_bp
from routes.properties import bp as properties_bp
from routes.quotes import bp as quotes_bp
from routes.weather import bp as weather_bp
from routes.visits import bp as visits_bp
from routes.crew import bp as crew_bp
from routes.plans import bp as plans_bp
from routes.invoices import bp as invoices_bp
from routes.claims import bp as claims_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp, customers_bp, technicians_bp, routes_bp, properties_bp,
        quotes_bp, weather_bp, visits_bp, crew_bp, plans_bp,
        invoices_bp, claims_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route. Auth still must be evaluated first per the pipeline,
        # but a path that matches no rule is genuinely not found.
        return error_response("ERR_INVALID_REQUEST", "Unknown route", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
