"""Flask entry point for the Wedding Planning API."""
import os
import threading

from flask import Flask, request, g

import db
from errors import APIError
from middleware import authenticate
from response import error_response


# Global serialization lock — coarse but sufficient for an in-memory
# implementation of an API whose concurrency rules say "first writer wins".
_GLOBAL_LOCK = threading.RLock()


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _before():
        if request.method == "OPTIONS":
            return
        _GLOBAL_LOCK.acquire()
        g._lock_held = True
        try:
            authenticate()
        except APIError as e:
            _release_lock()
            return error_response(e.error_id, e.message, e.http_status)

    @app.teardown_request
    def _teardown(exc):
        _release_lock()

    def _release_lock():
        if getattr(g, "_lock_held", False):
            try:
                _GLOBAL_LOCK.release()
            except RuntimeError:
                pass
            g._lock_held = False

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # 404 — likely an unmapped route. We surface a generic project-not-found-style envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INTERNAL", str(e), 500)

    # Register blueprints
    from routes.projects import bp as projects_bp
    from routes.templates import bp as templates_bp
    from routes.milestones import bp as milestones_bp
    from routes.vendors import bp as vendors_bp
    from routes.contracts import bp as contracts_bp
    from routes.change_orders import bp as change_orders_bp
    from routes.settlements import bp as settlements_bp
    from routes.timeline import bp as timeline_bp
    from routes.guests import bp as guests_bp
    from routes.audit import bp as audit_bp
    from routes.hooks import bp as hooks_bp

    app.register_blueprint(projects_bp)
    app.register_blueprint(templates_bp)
    app.register_blueprint(milestones_bp)
    app.register_blueprint(vendors_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(change_orders_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(timeline_bp)
    app.register_blueprint(guests_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(hooks_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
