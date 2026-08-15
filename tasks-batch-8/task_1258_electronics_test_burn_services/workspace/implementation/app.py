"""Entry point: Flask app assembly, error handlers, server runner."""
import os

from flask import Flask

from db import db
from envelope import error as error_response
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_core
    import routes_lots
    import routes_ops

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_lots.bp)
    app.register_blueprint(routes_ops.bp)

    @app.before_request
    def _acquire_lock():
        db.lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def _handle_405(err):
        return error_response(ApiError(ERR_INVALID_REQUEST, 400, "Method not allowed"))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return error_response(ApiError(ERR_INVALID_REQUEST, 500, f"Internal error: {err}")), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
