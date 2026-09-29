"""Open Data Portal & Dataset Publishing API.

Python + Flask, storage entirely in-memory (see core.Store).  The process boots
with a completely empty store and a logical clock pinned to 2026-08-01T00:00:00Z.
"""

import os
import sys

from flask import Flask, g, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import ApiError, error_body  # noqa: E402
from routes import artifacts, community, datasets, ops, pipelines, registry  # noqa: E402

API_PREFIX = "/open-data"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (registry.bp, datasets.bp, artifacts.bp, pipelines.bp, community.bp, ops.bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.before_request
    def _prepare():
        g.touched = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_body("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_body(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this route.", 405
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_body(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return error_body("ERR_INTERNAL", str(exc) or "Internal server error.", 500)

    @app.get("/health")
    def _health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
