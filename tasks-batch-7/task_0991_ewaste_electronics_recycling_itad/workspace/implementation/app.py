"""ITAD platform API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). Storage is in-memory only; the store
starts empty on every boot. All temporal logic reads the logical clock
(default 2026-05-01T00:00:00Z).
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import (accounts, batches, certificates, items, listings,
                    manifests, misc, policies, recyclers, sanitizations,
                    settlements)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (accounts, recyclers, policies, manifests, items,
                   sanitizations, listings, batches, settlements,
                   certificates, misc):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(500)
    def handle_internal(err):
        return error_response("ERR_INTERNAL", 500, "internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
