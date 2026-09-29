"""Emergency Food Assistance Commodity Allocation API.

A single Flask process holding the whole program state in memory. Nothing is
seeded: every entity is created through the API, and a fresh process starts
completely empty with the logical clock at its default instant (PRD §2.4).
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_config
import routes_inventory
import routes_program
from db import db
from errors import STATUS, ApiError
from response import error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_config.bp)
    app.register_blueprint(routes_inventory.bp)
    app.register_blueprint(routes_program.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_missing_route(exc):
        return error("ERR_NOT_FOUND", "No such route", 404)

    @app.errorhandler(405)
    def handle_bad_method(exc):
        return error("ERR_NOT_FOUND", "Method not allowed for this route", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            # a malformed JSON body is an invalid request, never a 400
            return error("ERR_INVALID_REQUEST", "The request body is not valid JSON", 422)
        if exc.code in (401, 403, 404, 405, 409, 412, 422):
            return error("ERR_INVALID_REQUEST", exc.description or "Invalid request", 422)
        return error("ERR_INTERNAL", exc.description or "Internal error", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return error("ERR_INTERNAL", "Internal server error", 500)

    # defensive: STATUS is the single source of truth for error status codes
    app.config["ERROR_STATUS"] = STATUS
    db.reset()
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
