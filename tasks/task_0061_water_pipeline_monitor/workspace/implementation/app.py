"""Water Pipeline Monitor API — Flask entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    from routes.networks import bp as networks_bp
    from routes.topology import bp as topology_bp
    from routes.dmas import bp as dmas_bp
    from routes.devices import bp as devices_bp
    from routes.alerts import bp as alerts_bp
    from routes.investigations import bp as investigations_bp
    from routes.work_orders import bp as work_orders_bp
    from routes.audit import bp as audit_bp

    for bp in (
        networks_bp,
        topology_bp,
        dmas_bp,
        devices_bp,
        alerts_bp,
        investigations_bp,
        work_orders_bp,
        audit_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Route or resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_BAD_REQUEST", "Method not allowed", 400)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_BAD_REQUEST", "Bad request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exc(e):
        return error_response("ERR_BAD_REQUEST", e.description or str(e), e.code or 400)

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_BAD_REQUEST", str(e) or "Internal error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
