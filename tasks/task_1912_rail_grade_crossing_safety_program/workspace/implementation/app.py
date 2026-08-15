"""Rail Crossing Safety API — Flask entry point.

Boot contract (INSTRUCTION.md): foreground process, 0.0.0.0:$PORT (default
10000), HTTP-ready within 60s, no state carried across restarts.
"""
import os
import threading

from flask import Flask

from errors import ApiError
from response import error_response


class _SerializedWsgi:
    """Serialize request handling through one process-wide lock.

    The in-memory store's check-then-act sequences (uniqueness, OCC, window
    overlap) stay atomic under the threaded development server.
    """

    def __init__(self, wsgi_app):
        self._wsgi_app = wsgi_app
        self._lock = threading.RLock()

    def __call__(self, environ, start_response):
        with self._lock:
            result = self._wsgi_app(environ, start_response)
            try:
                return list(result)
            finally:
                close = getattr(result, "close", None)
                if close is not None:
                    close()


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    from routes import register_blueprints

    register_blueprints(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def _handle_not_found(err):
        return error_response("ERR_NOT_FOUND", 404, "The requested resource does not exist")

    @app.errorhandler(405)
    def _handle_method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.http_status, err.message)
        return error_response("ERR_INTERNAL", 500, f"Internal server error: {err}")

    return app


app = create_app()
app.wsgi_app = _SerializedWsgi(app.wsgi_app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
