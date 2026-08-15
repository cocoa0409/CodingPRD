"""Youth Club Site Operations API — Flask entry point.

Storage is purely in-memory (see db.py) and starts empty on every boot; the
logical clock starts at exactly 2026-08-01T00:00:00Z before any override call.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
import routes.core_ops as core_ops
import routes.day_ops as day_ops

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(core_ops.bp)
app.register_blueprint(day_ops.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(HTTPException)
def handle_http_error(e):
    # Map unmatched routes / wrong methods / malformed requests into the error
    # envelope without leaking Flask HTML pages.
    from errors import err as make_err
    if e.code == 404:
        api_err = make_err("ERR_NOT_FOUND", "resource not found")
    elif e.code == 400:
        api_err = make_err("ERR_VALIDATION", "malformed request")
    else:
        api_err = make_err("ERR_VALIDATION", e.name)
        api_err.http_status = e.code if e.code and 400 <= e.code < 500 else 400
    return error_response(api_err)


@app.errorhandler(Exception)
def handle_unexpected(e):
    from errors import err as make_err
    api_err = make_err("ERR_VALIDATION", "unexpected server error: %s" % e)
    api_err.http_status = 500
    return error_response(api_err)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
