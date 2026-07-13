"""Identity Theft Protection API — entry point.

In-memory store only. Nothing is seeded at startup: every entity a caller needs
is constructed through the declared API surface.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import alerts, bureau, cases, claims, clock, plans, specialists, subscribers
from routes import wallet


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(plans.bp)
    app.register_blueprint(subscribers.bp)
    app.register_blueprint(bureau.bp)
    app.register_blueprint(wallet.bp)
    app.register_blueprint(alerts.bp)
    app.register_blueprint(cases.bp)
    app.register_blueprint(specialists.bp)
    app.register_blueprint(claims.bp)
    app.register_blueprint(clock.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(err):
        if err.code == 404:
            return error_response(ApiError("ERR_SUBSCRIBER_NOT_FOUND", "Resource not found."))
        if err.code in (400, 405, 415):
            return error_response(ApiError("ERR_INVALID_REQUEST", err.description))
        return error_response(ApiError("ERR_INVALID_REQUEST", err.description))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):  # pragma: no cover
        app.logger.exception(err)
        return error_response(ApiError("ERR_INVALID_REQUEST", "Unexpected server error."))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
