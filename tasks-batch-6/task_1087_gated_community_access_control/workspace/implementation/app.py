import os

from flask import Flask

from core import ApiError, error_response
import routes_core
import routes_vehicle
import routes_pass
import routes_amenity
import routes_patrol
import routes_violation


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_vehicle.bp)
    app.register_blueprint(routes_pass.bp)
    app.register_blueprint(routes_amenity.bp)
    app.register_blueprint(routes_patrol.bp)
    app.register_blueprint(routes_violation.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response(ApiError("ERR_VALIDATION", 400, "Unknown route"))

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response(ApiError("ERR_VALIDATION", 400, "Method not allowed"))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False)
