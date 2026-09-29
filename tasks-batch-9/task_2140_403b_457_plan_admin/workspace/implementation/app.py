"""403(b) & 457 Plan Administration API."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import accounts, core, elections, isa, movements, participants, remittance, requests


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (core.bp, isa.bp, participants.bp, accounts.bp, elections.bp,
                      remittance.bp, requests.bp, movements.bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return envelope.error("ERR_INVALID_REQUEST", "Unknown resource path.", 404)
        if exc.code == 405:
            return envelope.error("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if exc.code and 400 <= exc.code < 500:
            return envelope.error("ERR_INVALID_REQUEST", exc.description or "Bad request.",
                                  exc.code)
        return envelope.error("ERR_INTERNAL", exc.description or "Internal error.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return envelope.error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
