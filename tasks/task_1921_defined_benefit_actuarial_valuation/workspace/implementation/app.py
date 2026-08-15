"""Entry point: Flask app, error handlers, route registration."""

import os
import threading
from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

# Serialize request handling; the in-memory store is shared.
_REQUEST_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _REQUEST_LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    _REQUEST_LOCK.release()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(400)
def handle_400(err):
    return error_response(ERR_VALIDATION, 400, "Bad request")


@app.errorhandler(Exception)
def handle_exception(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    import traceback
    traceback.print_exc()
    return error_response(ERR_VALIDATION, 400, f"Unhandled error: {err}")


# register blueprints
from routes.plans import bp as plans_bp
from routes.census import bp as census_bp
from routes.assumptions import bp as assumptions_bp
from routes.assets import bp as assets_bp
from routes.runs import bp as runs_bp
from routes.funding import bp as funding_bp
from routes.filings import bp as filings_bp

app.register_blueprint(plans_bp)
app.register_blueprint(census_bp)
app.register_blueprint(assumptions_bp)
app.register_blueprint(assets_bp)
app.register_blueprint(runs_bp)
app.register_blueprint(funding_bp)
app.register_blueprint(filings_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
