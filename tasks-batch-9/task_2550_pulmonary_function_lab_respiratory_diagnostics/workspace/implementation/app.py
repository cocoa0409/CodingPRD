"""Pulmonary Function Lab API -- application entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERROR_STATUS, DEFAULT_MESSAGES
from responses import error_response

API_PREFIX = "/pft-lab"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:
        app.config["JSON_SORT_KEYS"] = False

    from r_devices import bp as devices_bp
    from r_registry import bp as registry_bp
    from r_orders import bp as orders_bp
    from r_sessions import bp as sessions_bp
    from r_challenge import bp as challenge_bp
    from r_reports import bp as reports_bp

    for blueprint in (devices_bp, registry_bp, orders_bp, sessions_bp,
                      challenge_bp, reports_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            error_id = "ERR_NOT_FOUND"
        elif exc.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif exc.code and exc.code < 500:
            error_id = "ERR_INVALID_REQUEST"
        else:
            error_id = "ERR_INTERNAL"
        status = exc.code or ERROR_STATUS.get(error_id, 400)
        return error_response(error_id,
                              exc.description or DEFAULT_MESSAGES.get(error_id),
                              status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", str(exc) or "Internal error.",
                              500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
