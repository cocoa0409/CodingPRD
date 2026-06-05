"""Flask entry point. Reads $PORT, binds 0.0.0.0, registers routes and error handlers."""
import os
import sys

from flask import Flask, request, g
from werkzeug.exceptions import HTTPException

import db
import response as R
from errors import APIError
import errors as E
import middleware as M
from routes import bp


def create_app():
    app = Flask(__name__)
    # Keep payloads small and avoid HTML responses for routing/method errors.
    app.url_map.strict_slashes = False

    @app.before_request
    def _before():
        # Assign a request id early so error handlers can emit it.
        g.api_request_id = db.new_request_id()
        # Authentication: skip OPTIONS preflight if any
        if request.method == "OPTIONS":
            return None
        M.authenticate()

    @app.errorhandler(APIError)
    def handle_api_error(err):
        return R.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_err):
        return R.error(E.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_err):
        return R.error(E.ERR_INVALID_REQUEST, "Method not allowed.", 400)

    @app.errorhandler(400)
    def handle_400(_err):
        return R.error(E.ERR_INVALID_REQUEST, "Bad request.", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        if err.code == 401:
            return R.error(E.ERR_UNAUTHENTICATED, "Unauthenticated.", 401)
        if err.code == 403:
            return R.error(E.ERR_FORBIDDEN, "Forbidden.", 403)
        if err.code == 404:
            return R.error(E.ERR_NOT_FOUND, "Resource not found.", 404)
        if err.code == 405:
            return R.error(E.ERR_INVALID_REQUEST, "Method not allowed.", 400)
        if err.code == 415:
            return R.error(E.ERR_INVALID_REQUEST, "Unsupported media type.", 400)
        return R.error(E.ERR_INVALID_REQUEST, str(err), err.code or 400)

    @app.errorhandler(Exception)
    def handle_exception(err):
        # Catch-all: log to stderr, return generic 500-flavored ERR_INVALID_REQUEST.
        print(f"[unhandled] {type(err).__name__}: {err}", file=sys.stderr, flush=True)
        return R.error(E.ERR_INVALID_REQUEST, "Internal error.", 500)

    app.register_blueprint(bp)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Disable Flask debug/reloader so signals propagate cleanly under start.sh.
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
