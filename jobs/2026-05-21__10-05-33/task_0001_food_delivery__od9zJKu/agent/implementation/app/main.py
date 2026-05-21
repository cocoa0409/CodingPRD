"""Flask app entrypoint."""
from __future__ import annotations

import os

from flask import Flask, request

from .auth import load_auth
from .envelope import APIError, error


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth():
        # Health check bypass
        if request.path in ("/", "/health"):
            return None
        if not request.path.startswith("/api/"):
            return None
        try:
            load_auth()
        except APIError as e:
            return error(e.error_id, e.message, e.status)

    @app.errorhandler(APIError)
    def _on_api_error(e: APIError):
        return error(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def _on_404(_e):
        return error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _on_405(_e):
        return error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(400)
    def _on_400(_e):
        return error("ERR_VALIDATION", "Malformed request", 422)

    @app.errorhandler(Exception)
    def _on_exception(e):
        # Don't swallow APIError
        if isinstance(e, APIError):
            return error(e.error_id, e.message, e.status)
        import traceback
        traceback.print_exc()
        return error("ERR_VALIDATION", f"Internal error: {e}", 422)

    @app.route("/")
    def root():
        return {"ok": True}

    # Register all blueprints
    from .routes import register_all
    register_all(app)
    return app


def main():
    app = create_app()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
