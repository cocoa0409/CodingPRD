"""HOA Declarant Turnover API — entry point."""
import os

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

import auth
import response
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _before_request():
        g._touched = set()
        path = request.path or ""
        if path.startswith("/hoa") or path.startswith("/_clock"):
            auth.authenticate()

    @app.errorhandler(ApiError)
    def _api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return response.error_response(
                "ERR_NOT_FOUND", "Resource not found.", 404
            )
        if error.code == 405:
            return response.error_response(
                "ERR_NOT_FOUND", "Method not allowed for this path.", 404
            )
        if error.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Malformed request.", 400
            )
        return response.error_response(
            "ERR_INVALID_REQUEST", error.description or "Request failed.",
            error.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(error):  # pragma: no cover - defensive
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % error, 500
        )

    @app.get("/")
    @app.get("/health")
    def _health():
        return response.object_response({"status": "ok"})

    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
