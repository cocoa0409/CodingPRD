"""Entry point: Flask app, error handlers, blueprint registration.

Binds 0.0.0.0:$PORT (default 10000) in the foreground. All state lives in
process-local memory (db.store); nothing is seeded at startup.
"""

import os

from flask import Flask

from core import ApiError, err_not_found, err_resp
from routes import (channels, community, deals, moderation, ops, payouts,
                    revenue, streams, strikes, taxforms)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (channels, taxforms, revenue, payouts, community, moderation,
                   strikes, deals, streams, ops):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_resp(e)

    @app.errorhandler(404)
    def handle_404(e):
        return err_resp(err_not_found("Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return err_resp(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err_resp(ApiError("ERR_INVALID_REQUEST", 400, str(e)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
