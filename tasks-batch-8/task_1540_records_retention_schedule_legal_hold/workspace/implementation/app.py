"""Entry point: Flask app assembly, error handlers, request serialization
lock. All state is in-memory and starts empty on every boot."""
import os
import threading

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

# Serialize request handling: derived-state cascades must be atomic per
# request even when the WSGI server threads.
_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        _LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def _handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def _handle_generic(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 400, str(e))


from routes import registry, rules, records, holds, dispositions, misc

app.register_blueprint(registry.bp)
app.register_blueprint(rules.bp)
app.register_blueprint(records.bp)
app.register_blueprint(holds.bp)
app.register_blueprint(dispositions.bp)
app.register_blueprint(misc.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
