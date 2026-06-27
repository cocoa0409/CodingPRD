import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response


# Global request lock. The in-memory store (plain Python dicts) is shared across
# the WSGI server's worker threads; serializing each request's body eliminates
# "dictionary changed size during iteration" crashes and read-modify-write races
# on the OCC version fields, regardless of how many connections are serviced
# concurrently under load.
_REQUEST_LOCK = threading.Lock()

from routes.clock_routes import bp as clock_bp
from routes.vendor_routes import bp as vendor_bp
from routes.solicitation_routes import bp as solicitation_bp
from routes.proposal_routes import bp as proposal_bp
from routes.award_routes import bp as award_bp
from routes.contract_routes import bp as contract_bp
from routes.invoice_routes import bp as invoice_bp
from routes.modification_routes import bp as modification_bp
from routes.protest_routes import bp as protest_bp
from routes.cpars_routes import bp as cpars_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (clock_bp, vendor_bp, solicitation_bp, proposal_bp, award_bp,
               contract_bp, invoice_bp, modification_bp, protest_bp, cpars_bp):
        app.register_blueprint(bp)

    @app.before_request
    def _acquire_lock():
        # Serialize the whole request body. teardown_request always runs when the
        # request context is popped (even on unhandled exceptions), so the lock is
        # reliably released; the g flag guards against a double release.
        _REQUEST_LOCK.acquire()
        g._holds_request_lock = True

    @app.teardown_request
    def _release_lock(exc=None):
        if getattr(g, "_holds_request_lock", False):
            g._holds_request_lock = False
            _REQUEST_LOCK.release()

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> standard not-found envelope.
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed.")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 400, "Malformed request.")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map remaining werkzeug HTTP exceptions onto our envelope.
        if e.code == 404 or e.code == 405:
            return error_response("ERR_NOT_FOUND", 404, "Resource not found.")
        if e.code == 415:
            return error_response("ERR_INVALID_REQUEST", 400, "Unsupported media type.")
        return error_response("ERR_INVALID_REQUEST", e.code or 400, e.description or "Error.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        if isinstance(e, HTTPException):
            return handle_http_exception(e)
        return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        # Production-grade pure-Python WSGI server: robust keep-alive and
        # connection handling under concurrent load (the Werkzeug dev server can
        # reset connections, surfacing as BadStatusLine on the client).
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, _quiet=True)
    except ImportError:
        # Fallback to the dev server if waitress is somehow unavailable.
        app.run(host="0.0.0.0", port=port, threaded=True)
