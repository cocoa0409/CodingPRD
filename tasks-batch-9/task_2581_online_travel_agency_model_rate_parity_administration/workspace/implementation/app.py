"""Online Travel Agency model, rate-parity and placement administration API.

Storage is process-local and in-memory: every boot starts completely empty and
nothing is ever seeded. Tests build all state through the declared endpoints."""
import os

from flask import Flask, jsonify

import clock
import errors
import response
import routes
import store


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    store.reset()
    clock.reset()
    routes.register(app)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return response.error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return response.error("ERR_METHOD_NOT_ALLOWED",
                              "The method is not allowed for this resource.", 405)

    @app.errorhandler(400)
    def handle_400(_exc):
        return response.error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return response.error("ERR_INTERNAL", "Unexpected server error.", 500)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "now": clock.now_iso_ms()}), 200

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
