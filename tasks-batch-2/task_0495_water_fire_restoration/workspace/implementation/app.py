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
from routes.technician_routes import bp as technician_bp
from routes.equipment_routes import bp as equipment_bp
from routes.claim_routes import bp as claim_bp
from routes.job_routes import bp as job_bp
from routes.chamber_routes import bp as chamber_bp
from routes.reading_routes import bp as reading_bp
from routes.placement_routes import bp as placement_bp
from routes.estimate_routes import bp as estimate_bp
from routes.contents_routes import bp as contents_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (clock_bp, technician_bp, equipment_bp, claim_bp, job_bp,
               chamber_bp, reading_bp, placement_bp, estimate_bp, contents_bp):
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
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed.")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 422, "Malformed request.")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        if e.code in (404, 405):
            return error_response("ERR_NOT_FOUND", 404, "Resource not found.")
        if e.code == 415:
            return error_response("ERR_INVALID_REQUEST", 422, "Unsupported media type.")
        return error_response("ERR_INVALID_REQUEST", 422, e.description or "Error.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        if isinstance(e, HTTPException):
            return handle_http_exception(e)
        return error_response("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        # Production-grade pure-Python WSGI server: robust keep-alive and
        # connection handling under concurrent load.
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, _quiet=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
