"""Flask entry point — registers routes and error handlers."""
import os

from flask import Flask, Blueprint

from errors import ApiError
from response import error as error_response

from routes import ceremonies, venues, graduates, seating, diplomas, rehearsal, accommodations, vendors, clock


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    api = Blueprint("api", __name__, url_prefix="/api")
    ceremonies.register(api)
    venues.register(api)
    graduates.register(api)
    seating.register(api)
    diplomas.register(api)
    rehearsal.register(api)
    accommodations.register(api)
    vendors.register(api)
    clock.register(api)
    app.register_blueprint(api)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
