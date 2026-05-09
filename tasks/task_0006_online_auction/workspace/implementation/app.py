import os
import threading
import traceback

from flask import Flask, request

from errors import ApiError
from response import error as error_response

import db


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Global lock around every request to serialize mutations.
    _global_lock = threading.RLock()

    @app.before_request
    def _acquire_lock():
        # Acquire DB lock for the duration of the request.
        request._db_lock = db.lock()
        request._db_lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        lock_obj = getattr(request, "_db_lock", None)
        if lock_obj is not None:
            try:
                lock_obj.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response("ERR_INVALID_REQUEST", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(_):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(_):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", f"Internal error: {err}", 500)

    # Register blueprints
    from routes.sellers import bp as sellers_bp
    from routes.bidders import bp as bidders_bp
    from routes.lots import bp as lots_bp
    from routes.bids import bp as bids_bp
    from routes.proxies import bp as proxies_bp
    from routes.disputes import bp as disputes_bp
    from routes.events import bp as events_bp

    app.register_blueprint(sellers_bp)
    app.register_blueprint(bidders_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(bids_bp)
    app.register_blueprint(proxies_bp)
    app.register_blueprint(disputes_bp)
    app.register_blueprint(events_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
