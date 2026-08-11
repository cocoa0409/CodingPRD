"""Flask entry point. Registers routes, error handlers, binds 0.0.0.0:$PORT."""

import os

from flask import Flask

import errors
import response as R
from routes import bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return R.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return R.error(errors.ERR_NOT_FOUND, "not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return R.error(errors.ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(500)
    def handle_500(e):
        return R.error(errors.ERR_INVALID_REQUEST, "internal error", 500)

    app.register_blueprint(bp)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
