"""Marrow Donor Registry Search & Workup API -- application factory.

State lives only in process memory (see store.py) and starts empty on every
boot, which is what makes `--isolation per-test-server` reboots deterministic.
"""

import os

from flask import Flask

import routes_booking
import routes_candidate
import routes_donor
import routes_patient
import routes_registry
import routes_workup
import store
from envelope import error_body
from errors import ApiError

BLUEPRINT_MODULES = (
    routes_registry,
    routes_patient,
    routes_donor,
    routes_candidate,
    routes_workup,
    routes_booking,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for module in BLUEPRINT_MODULES:
        app.register_blueprint(module.bp)

    @app.before_request
    def _begin_request():
        store.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_body(err.error_id, err.message), err.http_status

    @app.errorhandler(404)
    def _not_found(_err):
        return error_body("ERR_INVALID_REQUEST", "Unknown resource path."), 404

    @app.errorhandler(405)
    def _not_allowed(_err):
        return error_body("ERR_INVALID_REQUEST",
                          "Method not allowed for this path."), 405

    @app.errorhandler(400)
    def _bad_request(_err):
        return error_body("ERR_INVALID_REQUEST", "Malformed request."), 400

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return _api_error(err)
        app.logger.exception("unhandled error: %s", err)
        return error_body("ERR_INVALID_REQUEST", "Unhandled server error."), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False, debug=False)
