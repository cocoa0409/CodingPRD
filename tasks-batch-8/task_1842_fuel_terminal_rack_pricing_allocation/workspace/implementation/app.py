"""Entry point: app factory, error handlers, route registration."""
import os

from flask import Flask

from db import lock
from errors import ApiError
from response import error_response, success_object
from routes import register_routes


def create_app():
    app = Flask(__name__)

    # Serialize request handling so each request's mutations are atomic.
    @app.before_request
    def _acquire():
        lock.acquire()

    @app.teardown_request
    def _release(exc):
        try:
            lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response("ERR_NOT_FOUND", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def _handle_internal(e):
        return error_response("ERR_INTERNAL", 500, str(e))

    register_routes(app)

    @app.get("/")
    def root():
        return success_object({})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
