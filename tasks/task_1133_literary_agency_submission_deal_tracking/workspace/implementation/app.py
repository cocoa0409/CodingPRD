"""Entry point: app factory, global lock, error handlers, blueprint wiring."""
import os

from flask import Flask

from core import LOCK, ApiError, error_response
import routes_agreements
import routes_offers
import routes_queries
import routes_roster
import routes_royalties


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (routes_roster, routes_queries, routes_agreements,
                   routes_offers, routes_royalties):
        app.register_blueprint(module.bp)

    @app.before_request
    def _acquire_lock():
        LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404,
                                       "resource not found"))

    @app.errorhandler(405)
    def _handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404,
                                       "resource not found"))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_INTERNAL", 500,
                                       "internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
