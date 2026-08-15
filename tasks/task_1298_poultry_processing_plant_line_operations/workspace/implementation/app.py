"""Flask entry point: app factory, error handlers, route registration."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.lines import bp as lines_bp
    from routes.shifts import bp as shifts_bp
    from routes.sanitation import bp as sanitation_bp
    from routes.waivers import bp as waivers_bp
    from routes.flock_lots import bp as flock_lots_bp
    from routes.line_runs import bp as line_runs_bp
    from routes.condemnations import bp as condemnations_bp
    from routes.utility import bp as utility_bp
    from routes.orders import bp as orders_bp
    from routes.deboning import bp as deboning_bp
    from routes.finished_lots import bp as finished_lots_bp
    from routes.clock import bp as clock_bp

    app.register_blueprint(lines_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(sanitation_bp)
    app.register_blueprint(waivers_bp)
    app.register_blueprint(flock_lots_bp)
    app.register_blueprint(line_runs_bp)
    app.register_blueprint(condemnations_bp)
    app.register_blueprint(utility_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(deboning_bp)
    app.register_blueprint(finished_lots_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError(ERR_NOT_FOUND, "Resource not found", 404))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError(ERR_NOT_FOUND, "Method not allowed", 404))

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ApiError(ERR_INVALID_REQUEST, "Malformed request", 400))

    @app.errorhandler(Exception)
    def handle_exception(err):
        return error_response(err)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
