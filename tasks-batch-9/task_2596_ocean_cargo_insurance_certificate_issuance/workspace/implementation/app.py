"""Ocean Cargo Insurance & Certificate Issuance API (Python + Flask, in-memory store).

Entry point: registers the route blueprints and the error handlers. The data store
starts completely empty on every boot -- nothing is seeded, preloaded or hardcoded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
import routes_certificates
import routes_claims
import routes_ga
import routes_premium
import routes_registry


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:  # Flask >= 2.3 moved the switch onto the json provider
        app.json.sort_keys = False
    except Exception:  # pragma: no cover
        pass

    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_certificates.bp)
    app.register_blueprint(routes_premium.bp)
    app.register_blueprint(routes_claims.bp)
    app.register_blueprint(routes_ga.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", "Resource not found.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if exc.code == 415:
            return error_response("ERR_INVALID_REQUEST", "Unsupported media type.", 400)
        if exc.code and exc.code < 500:
            return error_response("ERR_INVALID_REQUEST", exc.description or "Bad request.",
                                  exc.code)
        return error_response("ERR_INVALID_REQUEST", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INVALID_REQUEST", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
