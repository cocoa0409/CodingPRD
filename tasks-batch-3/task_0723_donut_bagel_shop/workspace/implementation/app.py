"""Entry point: app factory, request hooks, error handlers."""
import os

from flask import Flask, g

from core import ApiError, err_response, request_id, _now_iso_precise
from routes import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _assign_request_meta():
        g.api_request_id = request_id()
        g.api_request_ts = _now_iso_precise()

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return err_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _handle_404(e):
        return err_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _handle_405(e):
        return err_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return err_response(e.error_id, e.http_status, e.message)
        return err_response("ERR_INVALID_REQUEST", 422, str(e))

    app.register_blueprint(bp)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
