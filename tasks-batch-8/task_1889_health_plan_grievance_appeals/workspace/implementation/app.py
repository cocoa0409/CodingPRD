"""Health Plan Grievance Appeals API — Flask entry point.

Mounts all blueprints under /appeals, registers envelope-aware error
handlers, and serves 0.0.0.0:$PORT (default 10000) in the foreground.
"""

import os

from flask import Flask

from envelope import error_response
from errors import ApiError, not_found
from routes import audit, cases, clock, effectuations, ire, members
from routes import notifications, policies, providers, reopenings, reviews

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (clock, members, providers, policies, cases, reviews,
               notifications, ire, effectuations, reopenings, audit):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(not_found())


@app.errorhandler(405)
def handle_405(err):
    return error_response(not_found())


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_VALIDATION", 400, str(err)))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
