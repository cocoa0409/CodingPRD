"""Flask application factory and process entry point.

Every boot starts from a completely empty in-memory store: nothing is seeded,
preloaded or read from disk.
"""

import os

from flask import Flask, jsonify

import routes_events
import routes_money
import routes_reference
from envelope import error_body
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_reference.bp)
    app.register_blueprint(routes_events.bp)
    app.register_blueprint(routes_money.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(400)
    def _bad_request(exc):
        return jsonify(error_body("ERR_VALIDATION", "Malformed request.")), 400

    @app.errorhandler(404)
    def _not_found(exc):
        return jsonify(error_body("ERR_RESOURCE_NOT_FOUND", "No such route.")), 404

    @app.errorhandler(405)
    def _not_allowed(exc):
        return (
            jsonify(error_body("ERR_VALIDATION", "Method not allowed for this route.")),
            405,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return jsonify(error_body(exc.error_id, exc.message)), exc.http_status
        return (
            jsonify(error_body("ERR_VALIDATION", "Unhandled server error: %s" % (exc,))),
            500,
        )

    @app.get("/_health")
    def _health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
