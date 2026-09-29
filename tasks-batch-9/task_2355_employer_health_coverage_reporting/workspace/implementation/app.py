"""Employer Health Coverage Reporting (ALE reporting) API.

Boots an empty in-memory store on every process start; nothing is ever seeded.
"""

import os

from flask import Flask, jsonify, request

import db
import envelope
from errors import ApiError

API_PREFIX = "/ale-reporting"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    from routes import filing, forms, penalty, seasons, workforce

    for module in (seasons, workforce, forms, filing, penalty):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.before_request
    def _acquire():
        db.LOCK.acquire()

    @app.teardown_request
    def _release(exc=None):
        try:
            db.LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc)

    @app.errorhandler(404)
    def _not_found(_exc):
        return envelope.error_response(
            ApiError("ERR_RECORD_NOT_FOUND", "No such resource: %s." % request.path)
        )

    @app.errorhandler(405)
    def _bad_method(_exc):
        return envelope.error_response(
            ApiError("ERR_INVALID_REQUEST", "%s is not allowed here." % request.method)
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return envelope.error_response(exc)
        body = {
            "meta": {
                "api_request_id": envelope._request_id(),
                "api_request_timestamp": db.now_iso(),
            },
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(exc) or "Internal error."},
        }
        return jsonify(body), 500

    @app.get("/health")
    def _health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
