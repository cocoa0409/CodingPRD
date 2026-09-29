"""Short-term rental turnover & cleaning coordination API.

State lives entirely in process memory (see db.py); nothing is seeded at
startup, so a freshly launched process serves an empty world until clients
create entities through the declared endpoints.
"""

import os

from flask import Flask, jsonify

import errors
from errors import ApiError
from response import error_body
from routes import (
    assignments,
    audits,
    bookings,
    checklist_tasks,
    cleaners,
    clock,
    issues,
    properties,
    turnovers,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (properties, cleaners, bookings, turnovers, assignments,
                   checklist_tasks, issues, audits, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return jsonify(error_body(errors.ERR_INVALID_REQUEST,
                                 "The request payload is malformed.")), 400

    @app.errorhandler(404)
    def handle_not_found(exc):
        return jsonify(error_body(errors.ERR_INVALID_REQUEST,
                                 "No route matches the requested path.")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return jsonify(error_body(errors.ERR_INVALID_REQUEST,
                                 "That method is not allowed on this path.")), 405

    @app.errorhandler(415)
    def handle_unsupported_media(exc):
        return jsonify(error_body(errors.ERR_INVALID_REQUEST,
                                 "The request body must be JSON.")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        app.logger.exception("unhandled error")
        return jsonify(error_body("ERR_INTERNAL", str(exc) or "Unexpected server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=True, use_reloader=False)
