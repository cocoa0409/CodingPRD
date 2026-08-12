"""Adult Family Home Residential Care API — Flask entry point."""

import os
import traceback

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from util import error_response


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    import routes_a
    import routes_b
    import routes_c
    import routes_d
    import routes_e
    app.register_blueprint(routes_a.bp)
    app.register_blueprint(routes_b.bp)
    app.register_blueprint(routes_c.bp)
    app.register_blueprint(routes_d.bp)
    app.register_blueprint(routes_e.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND[0], 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND[0], 404, "resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.status, e.message)
        traceback.print_exc()
        return error_response(ERR_INVALID_REQUEST[0], 400, "unprocessable request")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
