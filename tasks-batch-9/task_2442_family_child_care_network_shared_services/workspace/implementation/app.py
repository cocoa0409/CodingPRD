"""Family Child Care Network API — Flask application factory and entry point.

State lives in process memory only (see db.py); every boot starts empty.
"""
import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError

_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.agreements import bp as agreements_bp
    from routes.clock_api import bp as clock_bp
    from routes.enrollments import bp as enrollments_bp
    from routes.food import bp as food_bp
    from routes.orders import bp as orders_bp
    from routes.providers import bp as providers_bp
    from routes.quality import bp as quality_bp
    from routes.subsidy import bp as subsidy_bp
    from routes.substitutes import bp as substitutes_bp

    for blueprint in (
        providers_bp,
        agreements_bp,
        enrollments_bp,
        subsidy_bp,
        food_bp,
        substitutes_bp,
        quality_bp,
        orders_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _serialize():
        # One request at a time: every cascade must be observed as atomic.
        _LOCK.acquire()
        g.touched_ids = set()

    @app.teardown_request
    def _release(exc):
        try:
            _LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return response.error(
            "ERR_METHOD_NOT_ALLOWED", "The HTTP method is not allowed for this path.", 405
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return response.error(
            "ERR_INTERNAL", exc.description or "Unexpected error.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return response.error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

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
