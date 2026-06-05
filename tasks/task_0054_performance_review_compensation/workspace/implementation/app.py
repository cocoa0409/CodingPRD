"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.cycles import bp as cycles_bp
from routes.reviews import bp as reviews_bp
from routes.calibration import bp as calibration_bp
from routes.comp_plans import bp as comp_plans_bp
from routes.pip_cases import bp as pip_cases_bp


def create_app():
    app = Flask(__name__)

    app.register_blueprint(cycles_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(calibration_bp)
    app.register_blueprint(comp_plans_bp)
    app.register_blueprint(pip_cases_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_VALIDATION", str(e), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress (production-grade, pure-Python WSGI server) rather than
    # the Werkzeug dev server. Waitress binds the listening socket up front with
    # SO_REUSEADDR, services concurrent connections from a thread pool, and shuts
    # down cleanly on SIGTERM. This removes the bind race ("Address already in
    # use") and dropped-connection (BadStatusLine) flakes seen under the parallel
    # per-test-server restart sweep. API behavior is unchanged: the same WSGI
    # `app` object is served.
    from waitress import serve

    serve(app, host="0.0.0.0", port=port, threads=8)
