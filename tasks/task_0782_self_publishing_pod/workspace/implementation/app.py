"""Entry point: Flask app, blueprint registration, error handlers, launcher."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import ApiError, error_response

import routes_pub
import routes_format
import routes_price
import routes_asset
import routes_proof
import routes_dist
import routes_sales


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_pub.bp)
    app.register_blueprint(routes_format.bp)
    app.register_blueprint(routes_price.bp)
    app.register_blueprint(routes_asset.bp)
    app.register_blueprint(routes_proof.bp)
    app.register_blueprint(routes_dist.bp)
    app.register_blueprint(routes_sales.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _handle_http(err):
        code = err.code or 500
        if code == 404:
            return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))
        if code == 405:
            return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405))
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err), code if code < 500 else 400))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", "Internal server error", 500))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
