"""Military Household Goods PCS Move & Entitlement API.

Flask application factory and entry point.  All state lives in process memory
(see db.py); nothing is persisted and nothing is seeded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes import claims, clock, entitlements, members, notifications, ppm, progear, shipments
from routes import sit, tsps

HHG_BLUEPRINTS = (
    members.bp,
    entitlements.bp,
    tsps.bp,
    shipments.bp,
    progear.bp,
    sit.bp,
    claims.bp,
    ppm.bp,
    notifications.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in HHG_BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix="/hhg")
    app.register_blueprint(clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error(
            "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this resource.", 405
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return error(
                "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this resource.", 405
            )
        if exc.code and 400 <= exc.code < 500:
            return error("ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400)
        return error("ERR_INTERNAL", "Unexpected server error.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
