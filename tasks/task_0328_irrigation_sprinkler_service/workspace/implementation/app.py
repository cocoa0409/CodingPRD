"""Entry point: Flask app, blueprint registration, global error handlers.

In-memory store only — no seeding, no persistence. The store starts empty on
every boot; the test harness re-launches this process before every test.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.accounts import bp as accounts_bp
from routes.systems import bp as systems_bp
from routes.programs import bp as programs_bp
from routes.quotes import bp as quotes_bp
from routes.workorders import bp as workorders_bp
from routes.plans import bp as plans_bp
from routes.backflow import bp as backflow_bp
from routes.routing import bp as routing_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(accounts_bp)
    app.register_blueprint(systems_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(workorders_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(backflow_bp)
    app.register_blueprint(routing_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route — not an entity not-found. Keep the envelope shape.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
