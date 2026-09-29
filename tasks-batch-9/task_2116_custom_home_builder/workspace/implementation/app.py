"""Custom Home Builder API - entry point.

Storage is in-memory only and starts EMPTY on every boot: nothing is seeded,
preloaded or hardcoded.  Every row is created by callers through the declared
API surface.
"""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import AppError
from util import error_response

from routes.admin import bp as admin_bp
from routes.projects import bp as projects_bp
from routes.allowances import bp as allowances_bp
from routes.change_orders import bp as change_orders_bp
from routes.schedule import bp as schedule_bp
from routes.costs import bp as costs_bp
from routes.draws import bp as draws_bp
from routes.defects import bp as defects_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(admin_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(allowances_bp)
    app.register_blueprint(change_orders_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(costs_bp)
    app.register_blueprint(draws_bp)
    app.register_blueprint(defects_bp)

    lock = threading.RLock()

    @app.before_request
    def _serialise_request():
        lock.acquire()

    @app.teardown_request
    def _release_request(exc=None):
        try:
            lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(AppError)
    def _app_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested route does not exist.", 404)
        if err.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "The method is not allowed for this route.", 405)
        if err.code == 400:
            return error_response("ERR_INVALID_REQUEST", "The request is malformed.", 400)
        return error_response("ERR_INTERNAL", err.description or "Error", err.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(err):
        app.logger.exception("Unhandled error")
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    @app.get("/health")
    def _health():
        return {"status": "ok"}, 200

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
