"""Commercial Leasing API — Flask entry point."""
import os

from flask import Flask

from errors import APIError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.buildings import bp as buildings_bp
    from routes.units import bp as units_bp
    from routes.tenants import bp as tenants_bp
    from routes.leases import bp as leases_bp
    from routes.deposits import bp as deposits_bp
    from routes.fee_bills import bp as fee_bills_bp
    from routes.move_out import bp as move_out_bp
    from routes.audit import bp as audit_bp
    from routes.system import bp as system_bp

    for bp in (buildings_bp, units_bp, tenants_bp, leases_bp, deposits_bp,
               fee_bills_bp, move_out_bp, audit_bp, system_bp):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Route or resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION", "Bad request", 422)

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_VALIDATION", str(e) or "Internal error", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
