import os

from flask import Flask, g

from db import db
from errors import ApiError
from response import error_body

from routes.catalog import bp as catalog_bp
from routes.interpreters import bp as interpreters_bp
from routes.requests import bp as requests_bp
from routes.assignments import bp as assignments_bp
from routes.sessions import bp as sessions_bp
from routes.complaints import bp as complaints_bp
from routes.invoices import bp as invoices_bp
from routes.clock_ctl import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (catalog_bp, interpreters_bp, requests_bp, assignments_bp,
               sessions_bp, complaints_bp, invoices_bp, clock_bp):
        app.register_blueprint(bp)

    # Serialize all requests through the store lock for deterministic mutation.
    @app.before_request
    def _acquire():
        db.lock.acquire()
        g._locked = True

    @app.teardown_request
    def _release(exc):
        if getattr(g, "_locked", False):
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_body(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_body("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error_body("ERR_RESOURCE_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_body(e.error_id, e.message, e.http_status)
        return error_body("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
