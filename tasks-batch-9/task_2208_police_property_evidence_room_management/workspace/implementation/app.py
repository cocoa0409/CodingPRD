"""Police Evidence Room API — Flask application entry point.

Storage is in-memory only and starts completely empty on every boot: no entity
is seeded, preloaded or hardcoded anywhere in this service.
"""

import os

from flask import Flask, g

from envelope import error_body
from errors import ApiError, message_for, status_for
from routes import audit, cases, core, custody, disposition
from store import LOCK, begin_request, commit


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(core.bp)
    app.register_blueprint(cases.bp)
    app.register_blueprint(custody.bp)
    app.register_blueprint(disposition.bp)
    app.register_blueprint(audit.bp)

    @app.before_request
    def _before():
        LOCK.acquire()
        g._locked = True
        begin_request()

    @app.teardown_request
    def _teardown(exception=None):
        try:
            commit()
        finally:
            if getattr(g, "_locked", False):
                g._locked = False
                LOCK.release()

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_body(error.error_id, error.message), error.http_status

    @app.errorhandler(404)
    def _not_found(error):
        return error_body("ERR_NOT_FOUND", "The requested resource does not exist."), 404

    @app.errorhandler(405)
    def _not_allowed(error):
        return (
            error_body("ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path."),
            405,
        )

    @app.errorhandler(400)
    def _bad_request(error):
        return (
            error_body("ERR_INVALID_REQUEST", message_for("ERR_INVALID_REQUEST")),
            status_for("ERR_INVALID_REQUEST"),
        )

    @app.errorhandler(Exception)
    def _unhandled(error):
        if isinstance(error, ApiError):
            return _api_error(error)
        return error_body("ERR_INTERNAL", "An unexpected error occurred."), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
