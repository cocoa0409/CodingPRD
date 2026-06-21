"""Parks & Recreation Facility Reservation API — Flask entry point.

Registers all blueprints, installs error handlers that emit the standard error
envelope, and runs the server on 0.0.0.0:$PORT in the foreground. The in-memory
store starts empty on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error as error_response

from routes.patrons import bp as patrons_bp
from routes.facilities import bp as facilities_bp
from routes.insurance import bp as insurance_bp
from routes.permits import bp as permits_bp
from routes.payments import bp as payments_bp
from routes.leagues import bp as leagues_bp
from routes.lottery import bp as lottery_bp
from routes.ops import bp as ops_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(patrons_bp)
    app.register_blueprint(facilities_bp)
    app.register_blueprint(insurance_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(leagues_bp)
    app.register_blueprint(lottery_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map generic HTTP exceptions to the envelope; 4xx body parse issues etc.
        code = e.code or 500
        if code == 400:
            return error_response("ERR_VALIDATION", "Bad request", 422)
        return error_response("ERR_VALIDATION", str(e), code if code >= 400 else 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_VALIDATION", "Internal error: " + str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
