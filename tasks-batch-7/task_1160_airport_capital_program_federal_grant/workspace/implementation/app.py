"""Airport AIP Grants API — Flask entry point."""
import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from util import respond_error

app = Flask(__name__)

from routes import (applications, closeout, contracts, drawdowns, grants,  # noqa: E402
                    ops, phases, programs, sponsors)

for bp in (ops.bp, sponsors.bp, programs.bp, applications.bp, grants.bp,
           contracts.bp, drawdowns.bp, closeout.bp, phases.bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return respond_error(e.error_id, e.http_status, e.message)


@app.errorhandler(HTTPException)
def handle_http_error(e):
    # Unmatched paths / wrong methods surface through the fixed envelope.
    return respond_error("ERR_NOT_FOUND", e.code or 404,
                         e.description or "Not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    traceback.print_exc()
    return respond_error("ERR_INTERNAL", 500, str(e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
