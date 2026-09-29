"""Med-Surg Supply Distribution API - entry point."""
import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
import routes_catalog
import routes_inventory
import routes_logistics
import routes_orders

# Every request reads and writes the same in-memory store.  PRD 2.10 requires
# each request's side effects to land inside that request ("Nothing in this
# system settles later"), so a request is the unit of atomicity: one lock is
# held for the whole WSGI call.  Without it two worker threads can iterate a
# store dict (uniqueness scans, ledger recomputation) while a third inserts
# into it, which raises "dictionary changed size during iteration" and turns a
# perfectly valid write into a spurious error response.
_REQUEST_LOCK = threading.RLock()


class _SerialisedWsgi(object):
    """Serialise WSGI calls so each request mutates the store atomically."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with _REQUEST_LOCK:
            app_iter = self.wsgi_app(environ, start_response)
            try:
                # Materialise the body inside the lock; the response must be
                # fully determined before another request may touch the store.
                return [b"".join(app_iter)]
            finally:
                close = getattr(app_iter, "close", None)
                if close is not None:
                    close()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _init_request_state():
        g.dirty = {}
        g.fresh = set()

    app.register_blueprint(routes_catalog.bp)
    app.register_blueprint(routes_inventory.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_logistics.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(err):
        status = err.code or 500
        if status == 404:
            return error_response("ERR_VALIDATION", "Unknown resource path.", 404)
        if status == 405:
            return error_response("ERR_VALIDATION", "Method not allowed.", 405)
        return error_response("ERR_VALIDATION", err.description or "Bad request", status)

    @app.errorhandler(Exception)
    def _handle_unexpected(err):  # pragma: no cover - safety net
        return error_response("ERR_VALIDATION", "Unexpected server error: %s" % err, 400)

    app.wsgi_app = _SerialisedWsgi(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve as _serve
    except ImportError:  # pragma: no cover - dev-server fallback
        _serve = None
    if _serve is not None:
        # A production WSGI server: it keeps HTTP/1.1 connections alive, so a
        # client walking a workflow reuses one socket instead of opening a new
        # one per call, and it accepts on a dedicated loop with a deep backlog.
        _serve(app, host="0.0.0.0", port=port, threads=8, backlog=2048,
               connection_limit=1000, channel_timeout=300, asyncore_use_poll=True)
    else:
        app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
                use_reloader=False)
