"""Pawn Shop Loan & Inventory API — Flask entry point.

In-memory only; the store starts EMPTY on every boot and is never seeded.
Per-test-server isolation re-launches this process before every test.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.config import bp as config_bp
from routes.items import bp as items_bp
from routes.loans import bp as loans_bp
from routes.inventory import bp as inventory_bp
from routes.layaway import bp as layaway_bp
from routes.police import bp as police_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(layaway_bp)
    app.register_blueprint(police_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_response(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify(error_response("ERR_NOT_FOUND", "Resource not found.")), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify(error_response("ERR_NOT_FOUND", "Method not allowed.")), 404

    @app.errorhandler(400)
    def handle_400(e):
        return jsonify(error_response("ERR_INVALID_REQUEST", "Malformed request.")), 422

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return e
        return jsonify(error_response("ERR_INVALID_REQUEST", "Unexpected server error.")), 422

    return app


app = create_app()


if __name__ == "__main__":
    import logging
    import time

    # Silence werkzeug's per-request access log to reduce startup/serve overhead
    # under the parallel per-test reboot sweep.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    port = int(os.environ.get("PORT", "10000"))
    # Bind-retry loop: under per-test-server isolation the process is rebooted
    # before every test; the previous holder of the port may not have fully
    # released it, so retry the bind for a few seconds before giving up.
    deadline = time.time() + 20.0
    while True:
        try:
            app.run(host="0.0.0.0", port=port, threaded=True)
            break
        except OSError:
            if time.time() >= deadline:
                raise
            time.sleep(0.25)
