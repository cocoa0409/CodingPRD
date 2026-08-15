"""Entry point: Flask app, error handlers, request serialization, sweeps."""
import os
import threading

from flask import Flask

from errors import ApiError
from response import err
from routes import register_routes
from services import sweep_all

_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    register_routes(app)

    @app.before_request
    def _begin_request():
        # Serialize request handling so lazy sweeps and cascades are atomic
        # with the operation that observes them.
        _LOCK.acquire()
        try:
            sweep_all()
        except Exception:
            _LOCK.release()
            raise

    @app.teardown_request
    def _end_request(exc):
        try:
            _LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")

    @app.errorhandler(405)
    def handle_405(e):
        return err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
