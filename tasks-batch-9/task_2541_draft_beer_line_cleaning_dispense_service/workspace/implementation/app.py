"""Draft beer line cleaning and dispense service API.

Entry point: registers every route blueprint and the envelope-shaped error
handlers.  Storage is in-memory and starts completely empty on every boot --
nothing is seeded here or anywhere else.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_core
import routes_quality
import routes_registry
import routes_visits
import routes_work
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_visits.bp)
    app.register_blueprint(routes_work.bp)
    app.register_blueprint(routes_quality.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        # Unrouted paths and wrong verbs still answer in the standard envelope.
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "Request could not be routed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", str(exc) or "Unexpected error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
