"""Entry point: Flask app assembly, error handlers, post-mutation sweep."""
import os

from flask import Flask

from db import store
from errors import ApiError
from response import error_response, ok_object
from services import sweep


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (
        plants,
        permits,
        withdrawals,
        treatment,
        labtests,
        lines,
        lots,
        recalls,
        bottles,
        wash,
        reports,
    )

    for module in (
        plants,
        permits,
        withdrawals,
        treatment,
        labtests,
        lines,
        lots,
        recalls,
        bottles,
        wash,
        reports,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", "resource not found", 404))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", "method not allowed", 404))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err), 400))

    @app.after_request
    def sweep_after_mutation(response):
        # Posture and bottle-pool counters recompute synchronously on every
        # mutation of their inputs (safe no-op after failed/read-only calls).
        try:
            sweep()
        except Exception:
            pass
        return response

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
