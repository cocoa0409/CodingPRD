"""Master Data Stewardship & Governance API.

Boots a completely empty in-memory store on every process start: nothing is
seeded, preloaded or read from disk.  All state is created by API calls.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, g  # noqa: E402

import db  # noqa: E402
import response  # noqa: E402
import routes  # noqa: E402
from errors import ApiError  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in routes.BLUEPRINTS:
        app.register_blueprint(blueprint)

    # Requests are serialised: the store is plain Python dicts and every write
    # runs a multi-hop cascade that must be observed atomically.
    lock = threading.Lock()

    @app.before_request
    def _acquire():
        lock.acquire()
        g._store_lock = True
        g.touched_domains = []

    @app.teardown_request
    def _release(exception=None):
        if getattr(g, "_store_lock", False):
            g._store_lock = False
            try:
                lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return response.failure(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def _not_found(error):
        return response.failure("ERR_INVALID_REQUEST",
                                "The requested resource path does not exist.", 404)

    @app.errorhandler(405)
    def _not_allowed(error):
        return response.failure("ERR_INVALID_REQUEST",
                                "The HTTP method is not allowed on this path.", 405)

    @app.errorhandler(400)
    def _bad_request(error):
        return response.failure("ERR_INVALID_REQUEST",
                                "The request body or query string is invalid.", 400)

    @app.errorhandler(Exception)
    def _unhandled(error):
        if isinstance(error, ApiError):
            return response.failure(error.error_id, error.message, error.http_status)
        app.logger.exception("unhandled error")
        return response.failure("ERR_INVALID_REQUEST",
                                "The request could not be processed.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
