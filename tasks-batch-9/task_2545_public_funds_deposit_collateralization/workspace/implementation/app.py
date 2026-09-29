"""Public Funds Collateral API — Flask entry point.

The service exposes flat, top-level collections; there is no API prefix.
Storage is entirely in memory and starts empty on every boot.
"""

import os

from flask import Flask, g

import db
from errors import ApiError
from response import error_response
from services import state


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.registry import bp as registry_bp
    from routes.depositories import bp as depositories_bp
    from routes.accounts import bp as accounts_bp
    from routes.agreements import bp as agreements_bp
    from routes.collateral import bp as collateral_bp
    from routes.substitutions import bp as substitutions_bp
    from routes.margin import bp as margin_bp

    for blueprint in (
        registry_bp,
        depositories_bp,
        accounts_bp,
        agreements_bp,
        collateral_bp,
        substitutions_bp,
        margin_bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire():
        db.LOCK.acquire()
        g._holds_lock = True
        # Bring every derived field up to date before the handler reads any of
        # them; this never advances a state machine and never bumps a version.
        state.recompute_all()

    @app.teardown_request
    def _release(_exc):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            try:
                db.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response(
            "ERR_RESOURCE_NOT_FOUND", "The requested resource does not exist.", 404
        )

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return error_response(
            "ERR_RESOURCE_NOT_FOUND", "The requested resource does not exist.", 404
        )

    @app.errorhandler(400)
    def _bad_request(_exc):
        return error_response("ERR_INVALID_REQUEST", "The request is malformed.", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.status)
        return error_response("ERR_INVALID_REQUEST", "Unhandled error: %s" % exc, 400)

    return app


application = create_app()

if __name__ == "__main__":
    application.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
