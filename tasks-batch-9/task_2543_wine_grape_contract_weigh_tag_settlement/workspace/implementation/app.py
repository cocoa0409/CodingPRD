"""Wine Grape Contract & Weigh Tag Settlement API.

In-memory only: every row lives in the process dictionaries declared in
common.DB, nothing is seeded at startup, and a fresh process starts empty
with the logical clock reading 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_clock
import routes_contract
import routes_harvest
import routes_money
import routes_ref
import routes_scale
from common import ApiError, respond_error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_ref.bp)
    app.register_blueprint(routes_contract.bp)
    app.register_blueprint(routes_harvest.bp)
    app.register_blueprint(routes_scale.bp)
    app.register_blueprint(routes_money.bp)
    app.register_blueprint(routes_clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return respond_error(error.error_id, error.message, error.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            return respond_error("ERR_VALIDATION", "No such route.", 404)
        if error.code == 405:
            return respond_error("ERR_VALIDATION",
                                 "Method not allowed for this route.", 405)
        if error.code in (400, 415):
            return respond_error("ERR_VALIDATION",
                                 "The request body could not be read as JSON.", 422)
        return respond_error("ERR_VALIDATION",
                             error.description or "Request refused.",
                             error.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return respond_error("ERR_VALIDATION", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
