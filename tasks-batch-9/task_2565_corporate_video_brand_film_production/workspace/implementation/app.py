"""Corporate Video & Brand Film Production API.

Entry point: wires the response envelope, the error catalogue and every route
blueprint onto a Flask app.  Storage is in-memory and starts completely empty
on every boot -- nothing is seeded, preloaded or hardcoded.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from envelope import respond_error
from errors import ApiError
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    # Preserve the declared field order of every serialized resource.
    app.json.sort_keys = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _reset_touch_ledger():
        # One version bump per row per request, even when a transition and the
        # ledger movement it causes both touch the same row (PRD 2.4).
        g._touched_rows = set()

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return respond_error("ERR_NOT_FOUND", "No route matches the requested path.", 404)
        if exc.code == 405:
            return respond_error("ERR_METHOD_NOT_ALLOWED",
                                 "The HTTP method is not allowed for this path.", 405)
        if exc.code == 400:
            return respond_error("ERR_INVALID_REQUEST",
                                 "The request could not be parsed.", 400)
        return respond_error("ERR_REQUEST_FAILED", exc.description or "Request failed.",
                             exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return respond_error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
