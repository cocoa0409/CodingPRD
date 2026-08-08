"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from common import error_response
from errors import ApiError

from routes_core import bp_core
from routes_subscriptions import bp_subscriptions
from routes_products import bp_products
from routes_recalls import bp_recalls
from routes_claims import bp_claims
from routes_resolutions import bp_resolutions


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(bp_core)
    app.register_blueprint(bp_subscriptions)
    app.register_blueprint(bp_products)
    app.register_blueprint(bp_recalls)
    app.register_blueprint(bp_claims)
    app.register_blueprint(bp_resolutions)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "A referenced resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
