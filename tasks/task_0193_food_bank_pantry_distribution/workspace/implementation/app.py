"""Food Bank & Pantry Distribution API — entry point and error handlers."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.cold_storage import bp as cold_storage_bp
from routes.inventory import bp as inventory_bp
from routes.agencies import bp as agencies_bp
from routes.cycles import bp as cycles_bp
from routes.orders import bp as orders_bp
from routes.households import bp as households_bp
from routes.events import bp as events_bp
from routes.reports import bp as reports_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(cold_storage_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(agencies_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(households_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on a known path — treat as a forbidden role-less
        # malformed call. Map to ERR_NOT_FOUND-style 404? Per catalog there is no
        # 405 error; closest is route mismatch. Return 404 NOT_FOUND.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Body parse errors etc. surface as 400/415 — coerce to ERR_INVALID_REQUEST.
        return error_response("ERR_INVALID_REQUEST", e.description or "Invalid request.", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % e, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
