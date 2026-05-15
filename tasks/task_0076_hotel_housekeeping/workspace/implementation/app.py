"""Hotel Housekeeping API — Flask entry point."""

import os
from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound, MethodNotAllowed

from errors import APIError
from response import error_response

from routes.rooms import bp as rooms_bp
from routes.housekeepers import bp as housekeepers_bp
from routes.cleaning_tasks import bp as cleaning_tasks_bp
from routes.maintenance_tickets import bp as maintenance_bp
from routes.minibar import bp as minibar_bp
from routes.linen import bp as linen_bp
from routes.audit_logs import bp as audit_bp
from routes.events import bp as events_bp


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    app.register_blueprint(rooms_bp)
    app.register_blueprint(housekeepers_bp)
    app.register_blueprint(cleaning_tasks_bp)
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(minibar_bp)
    app.register_blueprint(linen_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(events_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(NotFound)
    def _handle_404(err):
        return error_response("ERR_INVALID_REQUEST", 404,
                              "Route not found")

    @app.errorhandler(MethodNotAllowed)
    def _handle_405(err):
        return error_response("ERR_INVALID_REQUEST", 405,
                              "Method not allowed")

    @app.errorhandler(HTTPException)
    def _handle_http_error(err):
        status = err.code or 500
        return error_response("ERR_INVALID_REQUEST", status if status >= 400 else 500,
                              err.description or "HTTP error")

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return error_response("ERR_INVALID_REQUEST", 500,
                              f"Internal error: {err}")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
