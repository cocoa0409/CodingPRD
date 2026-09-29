"""Motor Fuel Tax Licensing & Distributor Reporting API.

The store is empty on every boot; nothing is seeded, preloaded or hardcoded.
"""

import os
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError


class NumericJSONProvider(DefaultJSONProvider):
    """Money is an integer and gallons are JSON numbers -- never strings."""

    sort_keys = False

    @staticmethod
    def default(o):
        if isinstance(o, Decimal):
            return float(o)
        return DefaultJSONProvider.default(o)


def create_app():
    app = Flask(__name__)
    app.json = NumericJSONProvider(app)
    app.url_map.strict_slashes = False

    from routes.clock import bp as clock_bp
    from routes.licensees import bp as licensees_bp
    from routes.terminals import bp as terminals_bp
    from routes.removals import bp as removals_bp
    from routes.returns_bp import bp as returns_bp
    from routes.crossmatch import bp as crossmatch_bp
    from routes.refunds import bp as refunds_bp
    from routes.roadside import bp as roadside_bp
    from routes.audits import bp as audits_bp

    for blueprint in (licensees_bp, terminals_bp, removals_bp, returns_bp,
                      crossmatch_bp, refunds_bp, roadside_bp, audits_bp,
                      clock_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The requested path does not exist.", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST",
                "The method is not allowed on this path.", 405)
        if exc.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.",
            exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
