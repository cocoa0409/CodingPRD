"""Package Sortation Facility Operations & Peak Staffing API.

In-memory only: every process start begins with an empty store and the logical
clock pinned to 2026-08-01T00:00:00Z. Nothing is seeded or persisted.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, request_lock, respond_error
import routes_facility
import routes_inbound
import routes_labor
import routes_outbound


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_facility.bp)
    app.register_blueprint(routes_inbound.bp)
    app.register_blueprint(routes_labor.bp)
    app.register_blueprint(routes_outbound.bp)

    @app.before_request
    def _acquire():
        request_lock.acquire()

    @app.teardown_request
    def _release(_exc=None):
        try:
            request_lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return respond_error("ERR_INVALID_REQUEST", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return respond_error(
            "ERR_INVALID_REQUEST", "The HTTP method is not allowed for this resource.", 405
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return respond_error(
            "ERR_INVALID_REQUEST", exc.description or "The request could not be processed.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return respond_error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % (exc,), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
