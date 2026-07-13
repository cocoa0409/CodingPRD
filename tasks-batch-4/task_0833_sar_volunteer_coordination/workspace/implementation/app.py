"""Flask entry point for the SAR Volunteer Coordination API."""
import os

from flask import Flask

from errors import ApiError
from core import error_response
from routes_a import bp as bp_a
from routes_b import bp as bp_b


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp_a)
    app.register_blueprint(bp_b)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
