"""Express Locker API — Flask entry point."""

import os

from flask import Flask, request

from errors import APIError
from middleware import extract_auth
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    OPEN_PATHS = {"/healthz"}

    @app.before_request
    def _auth_check():
        if request.method == "OPTIONS":
            return None
        path = request.path
        if path in OPEN_PATHS:
            return None
        try:
            extract_auth()
        except APIError as exc:
            return error_response(exc.error_id, exc.message, exc.http_status)
        return None

    # Register blueprints
    from routes.machines import bp as machines_bp
    from routes.couriers import bp as couriers_bp
    from routes.parcels import bp as parcels_bp
    from routes.disputes import bp as disputes_bp
    from routes.settlements import bp as settlements_bp
    from routes.system import bp as system_bp

    app.register_blueprint(machines_bp)
    app.register_blueprint(couriers_bp)
    app.register_blueprint(parcels_bp)
    app.register_blueprint(disputes_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(system_bp)

    @app.route("/healthz", methods=["GET"])
    def _healthz():
        return {"status": "ok"}, 200

    @app.errorhandler(APIError)
    def _on_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _on_404(_e):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _on_405(_e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _on_uncaught(exc):
        if isinstance(exc, APIError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", f"Internal error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
