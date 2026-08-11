"""Entry point: Flask app, global error handlers, request serialization lock."""
import os
import threading

from flask import Flask

from errors import ApiError
from response import error_body
from routes import ALL_BLUEPRINTS

_lock = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.before_request
    def _serialize_requests():
        _lock.acquire()

    @app.teardown_request
    def _release_lock(exc):
        _lock.release()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_body(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _not_found(err):
        return error_body("ERR_INVALID_REQUEST", "Path not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_body("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _unhandled(err):
        return error_body("ERR_INVALID_REQUEST", str(err), 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
