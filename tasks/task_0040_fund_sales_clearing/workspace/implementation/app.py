"""Fund Sales and Clearing API — Flask entry point."""
import os
from flask import Flask

from errors import APIError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.investors import bp as investors_bp
    from routes.funds import bp as funds_bp
    from routes.nav import bp as nav_bp
    from routes.orders import bp as orders_bp
    from routes.dividends import bp as dividends_bp
    from routes.reconciliations import bp as reconciliations_bp
    from routes.audit_logs import bp as audit_bp
    from routes.system import bp as system_bp

    for bp in (investors_bp, funds_bp, nav_bp, orders_bp, dividends_bp,
               reconciliations_bp, audit_bp, system_bp):
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
