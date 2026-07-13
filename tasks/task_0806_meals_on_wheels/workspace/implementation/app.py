import os

from flask import Flask

import core
from core import ApiError

from routes.clients import bp as clients_bp
from routes.assessments import bp as assessments_bp
from routes.meal_plans import bp as meal_plans_bp
from routes.delivery_routes import bp as routes_bp
from routes.drivers import bp as drivers_bp
from routes.deliveries import bp as deliveries_bp
from routes.alerts import bp as alerts_bp
from routes.contributions import bp as contributions_bp
from routes.holds import bp as holds_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clients_bp,
        assessments_bp,
        meal_plans_bp,
        routes_bp,
        drivers_bp,
        deliveries_bp,
        alerts_bp,
        contributions_bp,
        holds_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return core.error_response(err)

    @app.errorhandler(404)
    def handle_404(_e):
        return core.error_response(ApiError("ERR_CLIENT_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(_e):
        return core.error_response(ApiError("ERR_UNAUTHORIZED", 403, "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return core.error_response(err)
        return core.error_response(ApiError("ERR_INTERNAL", 500, str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
