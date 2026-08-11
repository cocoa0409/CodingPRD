"""Accessibility Ramp & Home Modification API — entry point."""
import os

from flask import Flask

from core import ApiError, error_response
from domain import tick
from routes import ALL_BLUEPRINTS

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp)


@app.before_request
def _apply_time_driven_transitions():
    tick()


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_not_found(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404,
                                   "The requested resource does not exist"))


@app.errorhandler(405)
def _handle_method_not_allowed(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404,
                                   "The requested resource does not exist"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", 400,
                                   f"Request could not be processed: {err}"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    import time as _time
    with open("boot_trace.log", "a") as _f:
        _f.write(f"{_time.time():.3f} imports-done pid={os.getpid()} port={port}\n")
    app.run(host="0.0.0.0", port=port)
