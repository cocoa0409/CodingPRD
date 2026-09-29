"""Broadcast master control and playout operations API (PRD 2294).

Every byte of state lives in the in-memory dictionaries of store.py, so relaunching
this process through start.sh wipes the station clean: no seeding, no fixtures, no
persistence of any kind.
"""
import os
import subprocess
import sys

try:
    from flask import Flask, jsonify
except ModuleNotFoundError:  # pragma: no cover - first boot on a bare machine
    # The dependency check lives here rather than in start.sh so that the common
    # case (Flask already present) costs a single interpreter start: start.sh is
    # re-run before every reboot, and a second probe interpreter doubles the
    # boot latency of the process the harness is waiting on.
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
        cwd=os.path.dirname(os.path.abspath(__file__)), check=False,
    )
    os.execv(sys.executable, [sys.executable, *sys.argv])

import routes_asset
import routes_channel
import routes_fault
import routes_feed
import routes_item
import routes_override
import routes_plant
import routes_playlist
import routes_spot
import store
import timeutil
from errors import ERROR_STATUS, ApiError
from response import error_response

BLUEPRINTS = (
    routes_plant.bp,
    routes_channel.bp,
    routes_asset.bp,
    routes_playlist.bp,
    routes_item.bp,
    routes_feed.bp,
    routes_override.bp,
    routes_fault.bp,
    routes_spot.bp,
)


def envelope(error_id, message, status):
    body = {
        "meta": {"api_request_id": "req_error", "api_request_timestamp": timeutil.now_audit()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def open_transaction():
        # A request either applies every write it implies or none of them: the
        # ladder of PRD 2.8 refuses before anything is observable.
        store.begin()

    @app.teardown_request
    def close_transaction(err):
        if err is None:
            store.commit()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        store.rollback()
        return error_response(err)

    @app.errorhandler(404)
    def handle_missing_route(_err):
        return envelope("ERR_NOT_FOUND", "No resource is served at this path.", 404)

    @app.errorhandler(405)
    def handle_bad_method(_err):
        return envelope("ERR_METHOD_NOT_ALLOWED",
                        "That method is not served at this path.", 405)

    @app.errorhandler(415)
    def handle_bad_media(_err):
        return envelope("ERR_INVALID_FIELD_VALUE",
                        "The request body must be JSON.", ERROR_STATUS["ERR_INVALID_FIELD_VALUE"])

    @app.errorhandler(400)
    def handle_bad_request(err):
        store.rollback()
        if isinstance(err, ApiError):
            return error_response(err)
        return envelope("ERR_INVALID_FIELD_VALUE",
                        "The request body could not be read as JSON.",
                        ERROR_STATUS["ERR_INVALID_FIELD_VALUE"])

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        store.rollback()
        if isinstance(err, ApiError):
            return error_response(err)
        return envelope("ERR_INTERNAL", str(err) or "Unhandled server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=False)
