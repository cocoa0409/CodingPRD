"""Prior Authorization UM API — Flask entry point."""

import os
import threading

from flask import Flask

from errors import ApiError, ERR_INTERNAL, ERR_NOT_FOUND
from response import error as error_envelope
from routes import all_blueprints

# Serialize requests: multi-step cascades settle atomically inside the
# triggering request (immediate consistency model).
_lock = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    @app.before_request
    def _acquire():
        _lock.acquire()

    @app.teardown_request
    def _release(exc):
        try:
            _lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_envelope(err)

    @app.errorhandler(404)
    def _not_found(err):
        return error_envelope(
            ApiError(ERR_NOT_FOUND, 404, "A path resource id does not exist")
        )

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_envelope(
            ApiError(ERR_NOT_FOUND, 404, "A path resource id does not exist")
        )

    @app.errorhandler(Exception)
    def _unhandled(err):
        return error_envelope(
            ApiError(ERR_INTERNAL, 500, f"Internal error: {err}")
        )

    for bp in all_blueprints():
        app.register_blueprint(bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
