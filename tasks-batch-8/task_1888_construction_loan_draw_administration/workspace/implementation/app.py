import os

from flask import Flask, g

import db
from auth import auth_context
from errors import ApiError
from respond import error_response
from routes import register_blueprints


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _begin():
        # Serialize request handling: single-process in-memory store.
        db.lock.acquire()
        try:
            uid, role = auth_context()
            g.uid = uid
            g.role = role
        except Exception:
            db.lock.release()
            raise

    @app.teardown_request
    def _end(exc):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    register_blueprints(app)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.status, e.message)
        return error_response("ERR_INTERNAL", 500, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
