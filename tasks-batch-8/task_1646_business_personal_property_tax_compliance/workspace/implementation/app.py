"""BPP Tax Compliance API — Flask entry point.

Mounts all route modules under /bpp, registers the error handler producing
the standard error envelope (PRD §2.2), and runs the server on $PORT bound
to 0.0.0.0 in the foreground. All state is in-memory (db.Store); nothing is
persisted across process restarts and no entities are seeded at boot.
"""

import os

from flask import Flask

from db import Store
from errors import ApiError
from response import error as error_response

import routes_admin
import routes_assets
import routes_renditions
import routes_notices_appeals
import routes_bills
import routes_incentives


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    store = Store()
    app.config["STORE"] = store

    routes_admin.register(app, store)
    routes_assets.register(app, store)
    routes_renditions.register(app, store)
    routes_notices_appeals.register(app, store)
    routes_bills.register(app, store)
    routes_incentives.register(app, store)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", str(err), 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
