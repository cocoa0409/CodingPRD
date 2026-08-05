"""Community-Association Collections & Lien API — entry point."""
import os

from flask import Flask

import store as S
from web import ApiError, error_response
from routes_a import bp_a
from routes_b import bp_b


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _reset():
        S.reset_touched()

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _nf(_e):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def _mna(_e):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Method not allowed"))

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(ApiError("ERR_VALIDATION", 422, f"Unhandled: {e}"))

    app.register_blueprint(bp_a)
    app.register_blueprint(bp_b)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
