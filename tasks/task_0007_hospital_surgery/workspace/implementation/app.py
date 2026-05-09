import os

from flask import Flask, request

from errors import ApiError
from response import error as error_response
from routes_admin import bp as admin_bp
from routes_audit import bp as audit_bp
from routes_cases import bp as cases_bp
from routes_instruments import bp as instruments_bp
from routes_rooms import bp as rooms_bp
from routes_settlements import bp as settlements_bp
from routes_staff import bp as staff_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(rooms_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(instruments_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_not_found(_e):
        return error_response("ERR_INVALID_REQUEST", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(_e):
        return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed")

    @app.errorhandler(400)
    def handle_bad_request(_e):
        return error_response("ERR_INVALID_REQUEST", 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        # Fallback — should not normally trigger.
        return error_response("ERR_INVALID_REQUEST", 500, f"Unexpected error: {exc}")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
