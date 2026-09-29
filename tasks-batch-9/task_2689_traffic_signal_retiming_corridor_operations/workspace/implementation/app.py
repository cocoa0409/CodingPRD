"""Traffic Signal Retiming & Corridor Operations API.

Flask application factory and process entry point.  Storage is in-memory only
and starts completely empty on every boot; the harness relaunches this process
before every test, which is what gives each test a clean database.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import clock
import response
from errors import ApiError
from routes import (
    citizens,
    clock_admin,
    corridors,
    intersections,
    observations,
    plans,
    priority,
    projects,
)

BLUEPRINTS = (
    intersections.bp,
    corridors.bp,
    citizens.bp,
    projects.bp,
    plans.bp,
    priority.bp,
    observations.bp,
    clock_admin.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    clock.reset()

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return response.error("ERR_INVALID_REQUEST", "The request could not be parsed.", 422)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.error(
            "ERR_METHOD_NOT_ALLOWED", "That method is not allowed for this route.", 405
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return response.error(
                "ERR_HTTP_%s" % exc.code, exc.description or "Request refused.", exc.code
            )
        app.logger.exception("unhandled error")
        return response.error("ERR_INTERNAL", str(exc) or "Internal server error.", 500)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
