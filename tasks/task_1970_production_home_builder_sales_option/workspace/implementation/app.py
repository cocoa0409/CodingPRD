"""Production Home Builder Sales & Option Selection API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_body

from routes.clock import bp as clock_bp
from routes.communities import bp as communities_bp
from routes.phases import bp as phases_bp
from routes.plans import bp as plans_bp
from routes.catalog import bp as catalog_bp
from routes.lots import bp as lots_bp
from routes.buyers import bp as buyers_bp
from routes.agreements import bp as agreements_bp
from routes.selections import bp as selections_bp
from routes.milestones import bp as milestones_bp
from routes.incentives import bp as incentives_bp


def create_app():
    app = Flask(__name__)
    try:
        app.json.sort_keys = False
    except Exception:
        app.config["JSON_SORT_KEYS"] = False

    for bp in (
        clock_bp,
        communities_bp,
        phases_bp,
        plans_bp,
        catalog_bp,
        lots_bp,
        buyers_bp,
        agreements_bp,
        selections_bp,
        milestones_bp,
        incentives_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_body(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_body(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_body(ERR_INVALID_REQUEST, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", f"internal error: {exc}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Boot speed and quiet I/O matter under per-test-server isolation
    # (hundreds of SIGKILL/rebind cycles, concurrently with other suites on
    # the host): silence Werkzeug's per-request log lines so each reboot does
    # as little work as possible.
    import logging
    import werkzeug.serving

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    werkzeug.serving.WSGIRequestHandler.log = lambda *args, **kwargs: None
    app.run(host="0.0.0.0", port=port, threaded=True)
