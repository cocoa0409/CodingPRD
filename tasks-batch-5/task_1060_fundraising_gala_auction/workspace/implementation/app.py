"""Fundraising Gala & Auction API — Flask entrypoint.

Storage is in-memory only and starts completely empty on every boot.
"""
import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import ApiError, error_response  # noqa: E402
from routes.appeal import bp as appeal_bp  # noqa: E402
from routes.auction import bp as auction_bp  # noqa: E402
from routes.events import bp as events_bp  # noqa: E402
from routes.money import bp as money_bp  # noqa: E402
from routes.people import bp as people_bp  # noqa: E402
from routes.recon import bp as recon_bp  # noqa: E402
from routes.tickets import bp as tickets_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (events_bp, people_bp, tickets_bp, auction_bp,
                      appeal_bp, money_bp, recon_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_EVENT_NOT_FOUND", "unknown route"))
        if err.code == 405:
            return error_response(ApiError("ERR_INVALID_REQUEST", "method not allowed"))
        if err.code in (400, 415):
            return error_response(ApiError("ERR_INVALID_REQUEST", str(err)))
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err)))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_INVALID_REQUEST", "unexpected error: %s" % err))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
