"""Major appliance assembly plant API — Flask entry point.

State lives in process memory only (module `db`); every boot starts empty.
"""

import os

import response
import routes
from errors import ERROR_CATALOG, ApiError
from flask import Flask
from werkzeug.exceptions import HTTPException

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

routes.register(app)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(_exc):
    status, message = ERROR_CATALOG["ERR_NOT_FOUND"]
    return response.error("ERR_NOT_FOUND", message, status)


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    status, message = ERROR_CATALOG["ERR_METHOD_NOT_ALLOWED"]
    return response.error("ERR_METHOD_NOT_ALLOWED", message, status)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 404:
        return handle_not_found(exc)
    if exc.code == 405:
        return handle_method_not_allowed(exc)
    if exc.code and 400 <= exc.code < 500:
        status, message = ERROR_CATALOG["ERR_INVALID_REQUEST"]
        return response.error("ERR_INVALID_REQUEST", message, 400)
    status, message = ERROR_CATALOG["ERR_INTERNAL"]
    return response.error("ERR_INTERNAL", message, status)


@app.errorhandler(Exception)
def handle_unexpected(exc):  # pragma: no cover - safety net
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    if isinstance(exc, HTTPException):
        return handle_http_exception(exc)
    app.logger.exception("unhandled error: %s", exc)
    status, message = ERROR_CATALOG["ERR_INTERNAL"]
    return response.error("ERR_INTERNAL", message, status)


def _serve(port):
    """Serve on 0.0.0.0:port.

    Prefer waitress: Werkzeug's development server hard-codes
    ``Connection: close`` on every response (it cannot drain a request body
    before the next request line), so a suite of a few thousand calls opens a
    fresh TCP connection per call and intermittently trips over connection
    resets under load.  Waitress speaks HTTP/1.1 keep-alive and buffers the
    request body, so the same suite reuses one socket.  Fall back to the
    Flask/Werkzeug server when waitress is not installed.
    """
    try:
        from waitress import serve as waitress_serve
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
        return
    waitress_serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=8,
        backlog=1024,
        connection_limit=512,
        channel_timeout=300,
        clear_untrusted_proxy_headers=True,
        ident=None,
    )


if __name__ == "__main__":
    _serve(int(os.environ.get("PORT", "10000")))
