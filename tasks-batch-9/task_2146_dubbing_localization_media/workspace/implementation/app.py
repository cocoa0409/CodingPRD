"""Dubbing & Localization Media API - entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from responses import error_response
from routes import (casting, catalog, clock, mixing, orders, payments, people, qc,
                    script, sessions)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for module in (catalog, people, orders, script, casting, sessions, mixing,
                   qc, payments, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        return error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
