"""Residential Trash & Recycling Account API — Flask entry point.

In-memory store only; nothing seeded at startup. Boots clean on every process
launch (the harness restarts the server before each test).
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve with waitress (production-grade pure-Python WSGI server) instead of
    # the Werkzeug dev server. Werkzeug's dev server mishandles HTTP keep-alive
    # connection reuse under load: when the harness's pooled requests.Session
    # reuses an idle TCP connection that the server has just closed, the client
    # sees a BadStatusLine / "Connection aborted". Waitress handles the keep-alive
    # connection lifecycle correctly, eliminating the race.
    from waitress import serve

    serve(app, host="0.0.0.0", port=port, threads=8)
