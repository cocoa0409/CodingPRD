"""DMV Vehicle Registration & Title Transfer API — Flask entrypoint.

Wires up the blueprints, installs the standard error envelope on every
ApiError, and starts a Flask server bound to 0.0.0.0 on the PORT env var
(default 10000) per INSTRUCTION.md.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, make_error
from response import error as error_response
from routes.clock import clock_bp
from routes.emissions import emissions_bp
from routes.fee_ledger import ledger_bp
from routes.liens import liens_bp
from routes.owners import owners_bp
from routes.plates import plates_bp
from routes.real_id import real_id_bp
from routes.transfer_applications import transfer_bp
from routes.vehicles import vehicles_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(owners_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(real_id_bp)
    app.register_blueprint(emissions_bp)
    app.register_blueprint(liens_bp)
    app.register_blueprint(plates_bp)
    app.register_blueprint(transfer_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(clock_bp)

    # -----------------------------------------------------------------
    # Error handlers
    # -----------------------------------------------------------------
    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        err = make_error("ERR_RESOURCE_NOT_FOUND", "Route not found.")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(405)
    def handle_405(exc):
        err = make_error("ERR_VALIDATION", "Method not allowed.")
        return error_response(err.error_id, err.message, 405)

    @app.errorhandler(400)
    def handle_400(exc):
        err = make_error("ERR_VALIDATION", "Malformed request.")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):
        code = exc.code or 500
        if code == 404:
            return handle_404(exc)
        if code == 405:
            return handle_405(exc)
        if code == 400:
            return handle_400(exc)
        err = make_error("ERR_VALIDATION", exc.description or "HTTP exception")
        return error_response(err.error_id, err.message, code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        # Last-resort: surface as 500 with a generic envelope. Keeps the API
        # behaviour predictable when something genuinely unexpected happens.
        return error_response("ERR_VALIDATION", f"Internal error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
