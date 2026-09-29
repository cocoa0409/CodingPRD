"""Whole-Home Leak Detection & Insurer IoT Discount API."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
import routes_accounts
import routes_claims
import routes_devices
import routes_events
import routes_insurance
import routes_transfers


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_accounts.bp)
    app.register_blueprint(routes_devices.bp)
    app.register_blueprint(routes_events.bp)
    app.register_blueprint(routes_insurance.bp)
    app.register_blueprint(routes_claims.bp)
    app.register_blueprint(routes_transfers.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(
                ApiError("ERR_INVALID_REQUEST", "No route matches this path.", http_status=404)
            )
        if err.code == 405:
            return error_response(
                ApiError(
                    "ERR_INVALID_REQUEST",
                    "This method is not allowed on that path.",
                    http_status=405,
                )
            )
        if err.code in (400, 415):
            return error_response(
                ApiError("ERR_INVALID_REQUEST", "The request could not be parsed.")
            )
        return error_response(
            ApiError(
                "ERR_INVALID_REQUEST",
                err.description or "The request could not be served.",
                http_status=err.code or 500,
            )
        )

    @app.errorhandler(Exception)
    def _unhandled(err):  # pragma: no cover - defensive
        return error_response(
            ApiError("ERR_INVALID_REQUEST", "Internal error: %s" % err, http_status=500)
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
