"""Premium Audit API — Flask entry point.

In-memory store only; state starts empty on every process boot.
"""
import os
import signal

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response, _meta
from flask import jsonify

import routes_core
import routes_workorders
import routes_children
import routes_results

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_workorders.bp)
app.register_blueprint(routes_children.bp)
app.register_blueprint(routes_results.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(HTTPException)
def handle_http_exception(err):
    error_id = "ERR_NOT_FOUND" if err.code == 404 else (
        "ERR_METHOD_NOT_ALLOWED" if err.code == 405 else "ERR_HTTP")
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id,
                 "message": getattr(err, "description", str(err))},
    }
    return jsonify(body), (err.code or 500)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(err)


if __name__ == "__main__":
    # Resilience on shared hosts: this server runs under a test harness that
    # owns its lifecycle and tears it down with SIGKILL (uncatchable), which
    # always works. Stray SIGTERMs from unrelated processes on the host
    # (e.g. stale-pid terminate() calls after pid recycling) must not take
    # the server down mid-request, so SIGTERM is deliberately ignored.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
