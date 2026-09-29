"""Speakers Bureau Engagements API.

Flask application factory + launcher.  All state is held in process memory
(see db.py); nothing is seeded at startup and nothing is persisted to disk, so
every boot starts from an empty store.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    clock,
    compliance,
    contracts,
    engagements,
    feedback,
    money,
    pipeline,
    roster,
    travel,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(roster.bp)
    app.register_blueprint(pipeline.bp)
    app.register_blueprint(engagements.bp)
    app.register_blueprint(contracts.bp)
    app.register_blueprint(travel.bp)
    app.register_blueprint(feedback.bp)
    app.register_blueprint(money.bp)
    app.register_blueprint(compliance.bp)
    app.register_blueprint(clock.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error(
                "ERR_NOT_FOUND", "The requested path does not exist.", 404)
        if exc.code == 405:
            return response.error(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not allowed for this path.", 405)
        if exc.code in (400, 415):
            return response.error(
                "ERR_INVALID_REQUEST", "The request body is malformed.", 422)
        return response.error(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.",
            exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        return response.error("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    # Prefer waitress over the Werkzeug development server.  Werkzeug
    # unconditionally answers every request with `Connection: close`, so a
    # client is forced to open a brand-new TCP connection for each of the many
    # calls a single scenario makes; a long run then burns tens of thousands of
    # loopback ephemeral ports and, once the local port range fills up with
    # TIME_WAIT entries, the kernel starts resetting freshly opened
    # connections.  waitress honours HTTP/1.1 keep-alive and drains unread
    # request bodies before reusing a connection, which removes that churn
    # entirely.  The WSGI application, its routes and its responses are
    # identical either way; if waitress is unavailable we fall back to the
    # development server so the process always starts.
    try:
        from waitress import serve
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
                use_reloader=False)
    else:
        serve(app, host="0.0.0.0", port=port, threads=8)
