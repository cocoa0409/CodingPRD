import os

from flask import Flask

from db import store
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response
from routes import register_blueprints


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _acquire_lock():
        store.lock.acquire()

    @app.teardown_request
    def _release_lock(exc):
        store.lock.release()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ERR_NOT_FOUND, 404, "Referenced resource does not exist")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ERR_INVALID_REQUEST, 405, "Method not allowed")

    @app.errorhandler(Exception)
    def _internal(e):
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    register_blueprints(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
        debug=False,
    )
