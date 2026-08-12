"""Safety Supply & PPE Vending Program API — Flask entry point."""
import os
import threading

from flask import Flask, g

from auth import authenticate
from envelope import error_response
from errors import ApiError
import routes_catalog
import routes_finance
import routes_machines
import routes_people
import routes_service
import routes_vending

_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth():
        # Serialize requests: per-test-server reboots make this cheap, and it
        # keeps multi-resource cascades atomic.
        _LOCK.acquire()
        g._ppe_locked = True
        try:
            authenticate()
        except Exception:
            _LOCK.release()
            g._ppe_locked = False
            raise

    @app.teardown_request
    def _unlock(exc):
        if getattr(g, "_ppe_locked", False):
            g._ppe_locked = False
            try:
                _LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def _unhandled(e):
        app.logger.exception("unhandled error")
        return error_response("ERR_VALIDATION_FAILED", str(e), 400)

    app.register_blueprint(routes_catalog.bp)
    app.register_blueprint(routes_people.bp)
    app.register_blueprint(routes_machines.bp)
    app.register_blueprint(routes_vending.bp)
    app.register_blueprint(routes_service.bp)
    app.register_blueprint(routes_finance.bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
