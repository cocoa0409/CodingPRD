"""Entry point: Flask app, global error handlers, blueprint registration."""

import os

from flask import Flask

from envelope import error_body
from errors import ApiError, ERR_NOT_FOUND
import store
from routes import ALL_BLUEPRINTS

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False


@app.before_request
def _acquire_lock():
    store.STATE_LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        store.STATE_LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(e):
    return error_body(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _not_found(e):
    return error_body(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def _method_not_allowed(e):
    return error_body(ERR_NOT_FOUND, "Method not allowed", 405)


@app.errorhandler(Exception)
def _internal(e):
    return error_body("ERR_INTERNAL", str(e), 500)


for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
