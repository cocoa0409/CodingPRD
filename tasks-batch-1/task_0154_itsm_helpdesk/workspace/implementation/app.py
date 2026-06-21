"""ITSM Helpdesk API — Flask entry point.

In-memory only; the store starts EMPTY on every boot and is never seeded.
Per-test-server isolation re-launches this process before every test.
"""
import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.config import bp as config_bp
from routes.tickets import bp as tickets_bp
from routes.problems import bp as problems_bp
from routes.changes import bp as changes_bp
from routes.csat import bp as csat_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(problems_bp)
    app.register_blueprint(changes_bp)
    app.register_blueprint(csat_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_response(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return jsonify(error_response("ERR_NOT_FOUND", "Resource not found.")), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify(error_response("ERR_NOT_FOUND", "Method not allowed.")), 404

    @app.errorhandler(400)
    def handle_400(e):
        return jsonify(error_response("ERR_VALIDATION", "Malformed request.")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return e
        return jsonify(error_response("ERR_VALIDATION", "Unexpected server error.")), 400

    return app


app = create_app()


if __name__ == "__main__":
    import logging
    import time

    # Silence werkzeug's per-request access log. Under an 8x-parallel per-test
    # reboot sweep the synchronous access-log writes add startup/serve overhead
    # that can push a fresh boot past the runner's readiness deadline.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    port = int(os.environ.get("PORT", "10000"))
    # Bind-retry loop: under per-test-server isolation an 8-round parallel sweep
    # reboots this process before every test; the previous holder of the port may
    # not have fully released it yet, so a single app.run() can die with
    # "Address already in use" and the runner reports "could not be restarted".
    # Retry the bind for a few seconds before giving up.
    deadline = time.time() + 20.0
    while True:
        try:
            app.run(host="0.0.0.0", port=port, threaded=True)
            break
        except OSError:
            if time.time() >= deadline:
                raise
            time.sleep(0.25)
