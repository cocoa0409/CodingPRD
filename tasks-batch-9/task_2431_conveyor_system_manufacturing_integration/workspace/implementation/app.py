"""Conveyor Integration Delivery API — application entry point.

Storage is process-local and in-memory only: every boot starts from a
completely empty store with the logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.commercial import bp as commercial_bp
from routes.design import bp as design_bp
from routes.projects import bp as projects_bp
from routes.shop import bp as shop_bp
from routes.site import bp as site_bp
from store import store


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(projects_bp)
    app.register_blueprint(design_bp)
    app.register_blueprint(shop_bp)
    app.register_blueprint(site_bp)
    app.register_blueprint(commercial_bp)

    @app.before_request
    def _begin_request():
        # One request at a time: every handler mutates the shared store, and the
        # per-request version bookkeeping lives on `g`.
        g.touched_ids = set()
        store.lock.acquire()
        g.holds_lock = True

    @app.teardown_request
    def _end_request(_exception=None):
        if g.pop("holds_lock", False):
            try:
                store.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def _handle_not_found(_error):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(_error):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "The HTTP method is not allowed for this path.", 405
        )

    @app.errorhandler(HTTPException)
    def _handle_http_exception(error):
        status = error.code or 500
        error_id = "ERR_INVALID_REQUEST" if status < 500 else "ERR_INTERNAL"
        return error_response(error_id, error.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def _handle_unexpected(error):
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
