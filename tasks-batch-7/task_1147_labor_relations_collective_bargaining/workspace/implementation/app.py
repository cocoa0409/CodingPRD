"""Labor Relations & Collective Bargaining Administration API.

Entry point: registers blueprints, installs the error-envelope handlers, and runs
the server on 0.0.0.0:$PORT (default 10000). The store starts empty on every boot.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes import (
    agreements,
    clauses,
    clock_route,
    letters,
    practices,
    proposals,
    requests,
    scenarios,
    sessions,
    tasks,
    unions,
    votes,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (unions, agreements, clauses, sessions, proposals, scenarios,
               votes, letters, practices, requests, tasks, clock_route):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError(ERR_NOT_FOUND[0], "Resource not found", ERR_NOT_FOUND[1]))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError(ERR_NOT_FOUND[0], "Resource not found", ERR_NOT_FOUND[1]))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError(ERR_INVALID_REQUEST[0], "Malformed request", ERR_INVALID_REQUEST[1]))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
