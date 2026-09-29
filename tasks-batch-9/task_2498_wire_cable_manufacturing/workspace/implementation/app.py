"""Wire & cable mill API — Flask application factory and entry point.

State lives entirely in process memory (see db.py). Nothing is seeded: every
record in the system is created by a client through the declared endpoints, so a
fresh process is always an empty mill.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import clock
import response
import routes
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    # A fresh process starts with an empty store and the logical clock at its
    # documented default instant.
    clock.reset()

    for bp in routes.BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "No such route", 404)
        if exc.code == 405:
            return response.error(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed on this route", 405
            )
        if exc.code in (400, 415):
            return response.error(
                "ERR_INVALID_REQUEST", exc.description or "Malformed request", 400
            )
        return response.error(
            "ERR_INTERNAL", exc.description or "Request failed", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return response.error("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
