"""Brand Registry & Counterfeit Enforcement API.

The in-memory store starts EMPTY on every boot; no entity is seeded, preloaded
or hardcoded here.  Every row a caller needs is built through the public API.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError
from routes import core, enforce, legal, monitor


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    app.register_blueprint(core.bp)
    app.register_blueprint(monitor.bp)
    app.register_blueprint(enforce.bp)
    app.register_blueprint(legal.bp)

    @app.before_request
    def _open_request():
        db.lock.acquire()
        g._touched_rows = set()

    @app.teardown_request
    def _close_request(_exc=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return response.error("ERR_INVALID_REQUEST",
                              exc.description or exc.name, exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
