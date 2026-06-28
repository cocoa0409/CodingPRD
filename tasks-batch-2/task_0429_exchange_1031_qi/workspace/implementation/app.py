"""Application entry point: error handlers + blueprint registration.

In-memory storage only; the store starts EMPTY on every boot — nothing is seeded,
preloaded, or hardcoded. A fresh process therefore wipes all state. start.sh
re-invocation re-runs this module from scratch.
"""
import os

from flask import Flask

import errors
import response
from routes import (
    exchangers as exchangers_routes,
    exchanges as exchanges_routes,
    identifications as identifications_routes,
    replacements as replacements_routes,
    disbursements as disbursements_routes,
    clock as clock_routes,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(exchangers_routes.bp)
    app.register_blueprint(exchanges_routes.bp)
    app.register_blueprint(identifications_routes.bp)
    app.register_blueprint(replacements_routes.bp)
    app.register_blueprint(disbursements_routes.bp)
    app.register_blueprint(clock_routes.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route -> ERR_NOT_FOUND envelope (PRD §2.10 existence semantics).
        return response.error(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return response.error(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Re-raise ApiError so its dedicated handler runs.
        if isinstance(err, errors.ApiError):
            return response.error(err.error_id, err.message, err.http_status)
        return response.error(
            errors.ERR_INVALID_REQUEST, "Unexpected error: %s" % err, 422
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
