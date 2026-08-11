"""Renaissance Faire & Seasonal Attraction Operations API — entry point.

Flask app wiring: error handlers, blueprint registration, foreground run on
0.0.0.0:$PORT (default 10000).
"""
import os
import traceback

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_INVALID_REQUEST, 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_INVALID_REQUEST, 405, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        return error_response(ERR_INVALID_REQUEST, 500, "internal error: %s" % err)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
