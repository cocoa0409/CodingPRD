"""NEMT Medical Transport API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
Registers blueprints, installs uniform error handlers producing the standard
error envelope, and binds 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.billing import bp as billing_bp
from routes.legs import bp as legs_bp
from routes.members import bp as members_bp
from routes.providers import bp as providers_bp
from routes.standing_orders import bp as standing_orders_bp
from routes.testdrive import bp as testdrive_bp
from routes.trips import bp as trips_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(members_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(trips_bp)
    app.register_blueprint(legs_bp)
    app.register_blueprint(standing_orders_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(testdrive_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on an existing path — treat as not found for the
        # operation; no scaffold error covers 405, return a generic 404-shaped body.
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Malformed request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        # Surface unexpected server errors as a generic invalid-request to keep the
        # envelope uniform; should not happen in normal operation.
        return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
