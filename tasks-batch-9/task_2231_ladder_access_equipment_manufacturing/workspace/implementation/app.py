"""Ladder & Access Equipment Manufacturing Compliance API.

Single-process Flask application with a purely in-memory store: nothing is read
from or written to disk, and no entity data is seeded at boot, so every process
launch starts from an empty dataset with the logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, jsonify, request

import response
import store
import validate
from auth import authorize
from errors import ApiError
from routes import BLUEPRINTS

API_PREFIX = "/ladder-ops"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    # ------------------------------------------------------------------
    # logical clock (outside the /ladder-ops mount)
    # ------------------------------------------------------------------
    @app.post("/_clock/set_current_utc")
    @authorize("SystemOperator")
    def set_current_utc():
        data = validate.body()
        instant = validate.req_instant(data, "to_iso8601")
        store.set_clock(instant)
        return response.raw({"current_utc": response.fmt_instant(store.now())})

    # ------------------------------------------------------------------
    # request serialization: one request mutates the store at a time
    # ------------------------------------------------------------------
    @app.before_request
    def _acquire():
        store.request_lock.acquire()
        request.environ["_lock_held"] = True

    @app.teardown_request
    def _release(_exception=None):
        if request.environ.pop("_lock_held", None):
            try:
                store.request_lock.release()
            except RuntimeError:
                pass

    # ------------------------------------------------------------------
    # error handlers — every failure uses the standard envelope
    # ------------------------------------------------------------------
    @app.errorhandler(ApiError)
    def _api_error(error):
        return jsonify(response.error_body(error.error_id, error.message)), error.http_status

    @app.errorhandler(404)
    def _not_found(_error):
        return (
            jsonify(response.error_body("ERR_NOT_FOUND", "the requested resource does not exist")),
            404,
        )

    @app.errorhandler(405)
    def _method_not_allowed(_error):
        return (
            jsonify(
                response.error_body(
                    "ERR_METHOD_NOT_ALLOWED", "the method is not allowed for this resource"
                )
            ),
            405,
        )

    @app.errorhandler(Exception)
    def _unexpected(error):
        if isinstance(error, ApiError):
            return _api_error(error)
        app.logger.exception("unhandled error: %s", error)
        return jsonify(response.error_body("ERR_INTERNAL", str(error))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
