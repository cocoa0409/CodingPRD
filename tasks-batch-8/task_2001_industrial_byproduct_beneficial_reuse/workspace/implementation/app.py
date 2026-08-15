"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from common import ApiError, error_response
from routes.agreements import bp as agreements_bp
from routes.misc import bp as misc_bp
from routes.orgs import bp as orgs_bp
from routes.permits import bp as permits_bp
from routes.shipments import bp as shipments_bp
from routes.storage import bp as storage_bp
from routes.streams import bp as streams_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (orgs_bp, streams_bp, permits_bp, agreements_bp, shipments_bp,
               storage_bp, misc_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_response(ApiError("ERR_NOT_FOUND", 404,
                                       "Resource not found"))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
