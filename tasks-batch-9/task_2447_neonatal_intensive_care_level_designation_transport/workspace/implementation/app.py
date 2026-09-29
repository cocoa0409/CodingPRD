"""Neonatal Network API — application entry point.

State lives in process memory only (see db.py); a fresh process therefore starts
with every collection empty and nothing preloaded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import api_care
import api_network
import api_oversight
import api_referrals
import response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(api_network.bp)
    app.register_blueprint(api_referrals.bp)
    app.register_blueprint(api_care.bp)
    app.register_blueprint(api_oversight.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_INVALID_REQUEST",
                                  "No such endpoint.", 404)
        if exc.code == 405:
            return response.error("ERR_INVALID_REQUEST",
                                  "Method not allowed for this endpoint.", 405)
        if exc.code and exc.code < 500:
            return response.error("ERR_INVALID_REQUEST",
                                  exc.description or "The request is malformed.", 400)
        return response.error("ERR_INTERNAL", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
