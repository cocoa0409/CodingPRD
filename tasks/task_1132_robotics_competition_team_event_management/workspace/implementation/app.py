"""Entry point: Flask app assembly, error handlers, route registration."""
import os

from flask import Flask, Blueprint

import envelope
from db import request_lock
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND

from routes.events import bp as events_bp
from routes.registration import bp as registration_bp
from routes.procurement import bp as procurement_bp
from routes.matches import bp as matches_bp
from routes.alliances import bp as alliances_bp
from routes.awards import bp as awards_bp
from routes.flat import register_flat_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _acquire_lock():
        request_lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            request_lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return envelope.error_response(e)

    @app.errorhandler(404)
    def _handle_404(e):
        return envelope.error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def _handle_405(e):
        return envelope.error_response(ApiError(ERR_INVALID_REQUEST, 405, "Method not allowed"))

    @app.errorhandler(400)
    def _handle_400(e):
        if isinstance(e, ApiError):
            return envelope.error_response(e)
        return envelope.error_response(ApiError(ERR_INVALID_REQUEST, 400, "Bad request"))

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return envelope.error_response(e)
        return envelope.error_response(ApiError(ERR_INVALID_REQUEST, 500, "Internal server error"))

    app.register_blueprint(events_bp)
    app.register_blueprint(registration_bp)
    app.register_blueprint(procurement_bp)
    app.register_blueprint(matches_bp)
    app.register_blueprint(alliances_bp)
    app.register_blueprint(awards_bp)

    flat_bp = Blueprint("flat", __name__)
    register_flat_routes(flat_bp)
    app.register_blueprint(flat_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
