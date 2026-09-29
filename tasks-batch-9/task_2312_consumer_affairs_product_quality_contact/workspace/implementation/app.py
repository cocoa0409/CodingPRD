"""Consumer Affairs & Product Quality Contact API.

Single-process Flask service, in-memory storage only.  The store starts empty on
every boot: nothing is ever seeded, preloaded or hardcoded.
"""

import os

from flask import Flask, g, jsonify

import routes_contacts
import routes_goodwill
import routes_kits
import routes_reference
import routes_regulatory
import routes_templates
import routes_trends
from common import ApiError, error_body, request_lock


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        routes_reference,
        routes_contacts,
        routes_kits,
        routes_goodwill,
        routes_regulatory,
        routes_trends,
        routes_templates,
    ):
        app.register_blueprint(module.bp)

    # Every request is serialized: the whole store is shared mutable state and
    # several endpoints (the ops run in particular) read-modify-write across
    # many collections at once.
    @app.before_request
    def _acquire():
        request_lock.acquire()
        g._lock_held = True

    @app.teardown_request
    def _release(exc=None):
        if g.pop("_lock_held", False):
            try:
                request_lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(exc):
        return jsonify(error_body("ERR_VALIDATION", "unknown route")), 404

    @app.errorhandler(405)
    def _not_allowed(exc):
        return jsonify(error_body("ERR_VALIDATION", "method not allowed")), 405

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        app.logger.exception("unhandled error")
        return jsonify(error_body("ERR_VALIDATION", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
