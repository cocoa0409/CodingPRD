"""Resort-fee and ancillary-charge disclosure compliance API.

Entry point: blueprint registration, the error envelope handlers and the
foreground server. The store is in-memory and starts empty on every boot —
nothing is seeded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError

import routes_bookings
import routes_config
import routes_fees
import routes_guest
import routes_profiles
import routes_regulator


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_config.bp)
    app.register_blueprint(routes_fees.bp)
    app.register_blueprint(routes_profiles.bp)
    app.register_blueprint(routes_bookings.bp)
    app.register_blueprint(routes_guest.bp)
    app.register_blueprint(routes_regulator.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return envelope.error_response(
            "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this route.", 405)

    @app.errorhandler(400)
    def _bad_request(exc):
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "The request body could not be parsed.", 422)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return envelope.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request rejected.",
            exc.code if exc.code else 422)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        app.logger.exception("unhandled error")
        return envelope.error_response("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


application = create_app()

if __name__ == "__main__":
    application.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
        use_reloader=False,
    )
