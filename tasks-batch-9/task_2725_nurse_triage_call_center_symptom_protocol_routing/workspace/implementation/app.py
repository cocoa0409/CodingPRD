"""Nurse triage call centre — symptom protocol routing API.

A single-process Flask application whose entire state lives in memory (see
store.py). Nothing is seeded: a fresh process knows the rules of the business
and none of its data, which is what makes the per-test-server harness sound.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes.callbacks import bp as callbacks_bp
from routes.calls import bp as calls_bp
from routes.clock import bp as clock_bp
from routes.coverage import bp as coverage_bp
from routes.dispositions import bp as dispositions_bp
from routes.nurses import bp as nurses_bp
from routes.practices import bp as practices_bp
from routes.protocols import bp as protocols_bp
from routes.transfers import bp as transfers_bp

BLUEPRINTS = (practices_bp, coverage_bp, nurses_bp, protocols_bp, calls_bp,
              dispositions_bp, transfers_bp, callbacks_bp, clock_bp)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:                                # pragma: no cover
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        status = error.code or 500
        if status == 404:
            return error_response("ERR_INVALID_REQUEST", "No such resource.", 404)
        if status == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "That method is not allowed here.", 405)
        return error_response("ERR_INVALID_REQUEST",
                              error.description or "Request could not be served.",
                              status)

    @app.errorhandler(Exception)
    def handle_unexpected(error):                         # pragma: no cover
        return error_response("ERR_INVALID_REQUEST", "Unhandled server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # threaded=False keeps request handling serial, so the conserved counters and
    # ledgers can never interleave.
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
