"""College & Career Readiness API — Flask entry point.

In-memory only; the store starts empty on every boot and nothing is seeded.
Reads $PORT (default 10000), binds 0.0.0.0, runs in the foreground.
"""

import os

from flask import Flask, g

from util import ApiError, error_response, auth_context, ERR_NOT_FOUND
from routes import register_blueprints

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.before_request
def _authenticate():
    # Pipeline stage 1: X-User-Role and X-User-ID present, role recognized.
    uid, role = auth_context()
    g.user_id = uid
    g.user_role = role


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _not_found(_err):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(405)
def _method_not_allowed(_err):
    return error_response(ApiError(ERR_NOT_FOUND, 405, "Method not allowed"))


@app.errorhandler(500)
def _internal(_err):
    return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))


register_blueprints(app)


if __name__ == "__main__":
    # threaded=True: the per-test-server harness restarts the process between
    # tests; a threaded server keeps health polls responsive even while a
    # burst of requests is in flight, avoiding spurious restart timeouts.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
