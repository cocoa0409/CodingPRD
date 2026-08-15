"""Swim Meet Officiating API — Flask entry point."""

import os
import threading
import traceback

from flask import Flask

from errors import ERR_INVALID_REQUEST, ApiError
from response import err_response
from routes import register_routes

app = Flask(__name__)
register_routes(app)

# Serialize requests: the store is plain dicts; tests are sequential but the
# dev server is threaded, so guard the whole request cycle.
_LOCK = threading.RLock()


@app.before_request
def _acquire():
    _LOCK.acquire()


@app.teardown_request
def _release(exc):
    _LOCK.release()


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.message, e.status)


@app.errorhandler(404)
def handle_not_found(e):
    return err_response(ERR_INVALID_REQUEST, "route not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return err_response(ERR_INVALID_REQUEST, "method not allowed", 405)


@app.errorhandler(Exception)
def handle_exception(e):
    traceback.print_exc()
    return err_response("ERR_INTERNAL", str(e), 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
