"""Entry point: Flask app assembly, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_resp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Route modules register onto the shared core blueprint plus the flat one.
    import routes.core  # noqa: F401  (defines the core blueprint)
    import routes.charges  # noqa: F401
    import routes.purchase  # noqa: F401
    import routes.resolutions  # noqa: F401
    import routes.agreements  # noqa: F401
    import routes.meetings  # noqa: F401
    from routes.core import bp as core_bp
    from routes.flat import bp as flat_bp
    app.register_blueprint(core_bp)
    app.register_blueprint(flat_bp)

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_resp(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_resp("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_resp("ERR_NOT_FOUND", "Method not allowed", 405)

    @app.errorhandler(500)
    def handle_500(e):
        return error_resp("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
