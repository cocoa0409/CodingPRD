"""Municipal Court Diversion API — Flask entry point."""

import os
from flask import Flask

from errors import ApiError
from envelope import error_response

from routes_core import bp_core
from routes_diversion import bp_diversion
from routes_ledger import bp_ledger
from routes_lifecycle import bp_lifecycle


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(bp_core)
    app.register_blueprint(bp_diversion)
    app.register_blueprint(bp_ledger)
    app.register_blueprint(bp_lifecycle)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_VALIDATION", "resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_VALIDATION", "method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_VALIDATION", f"unexpected error: {err}"))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
