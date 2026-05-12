"""Home Nursing API — Flask entrypoint."""
import os

from flask import Flask

from errors import APIError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    from routes.nurses import bp as nurses_bp
    from routes.service_items import bp as si_bp
    from routes.orders import bp as orders_bp
    from routes.dispatches import bp as disp_bp
    from routes.packages import bp as pkg_bp
    from routes.payouts import bp as payouts_bp
    from routes.complaints import bp as comp_bp
    from routes.audit_and_hooks import bp as audit_bp

    for bp in (nurses_bp, si_bp, orders_bp, disp_bp, pkg_bp,
               payouts_bp, comp_bp, audit_bp):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_INVALID_REQUEST", "Route or resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e) or "Internal error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
