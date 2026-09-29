"""Correctional Food Service Operations API — Flask entrypoint.

Storage is in-memory only and starts completely empty on every boot: no
seeding, no preloading, no on-disk persistence of any kind.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, ERRORS, respond_error

from routes_contract import bp as contract_bp
from routes_menu import bp as menu_bp
from routes_roster import bp as roster_bp
from routes_forecast import bp as forecast_bp
from routes_batch import bp as batch_bp
from routes_security import bp as security_bp
from routes_service import bp as service_bp
from routes_grievance import bp as grievance_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (contract_bp, menu_bp, roster_bp, forecast_bp, batch_bp,
                      security_bp, service_bp, grievance_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return respond_error("ERR_NOT_FOUND", ERRORS["ERR_NOT_FOUND"][1], 404)
        if exc.code == 405:
            return respond_error("ERR_METHOD_NOT_ALLOWED",
                                 ERRORS["ERR_METHOD_NOT_ALLOWED"][1], 405)
        if exc.code == 400:
            return respond_error("ERR_INVALID_REQUEST",
                                 ERRORS["ERR_INVALID_REQUEST"][1], 400)
        return respond_error("ERR_INTERNAL", exc.description or "Error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return respond_error("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
