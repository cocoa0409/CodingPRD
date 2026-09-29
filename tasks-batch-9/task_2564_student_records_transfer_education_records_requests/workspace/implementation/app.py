"""Student Records Transfer & Education Records Requests API.

Flask application factory and error handlers.  All state lives in process memory
(see common.STORE); nothing is persisted and nothing is seeded at boot.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from common import ApiError
from response import error_body

import routes_amendments
import routes_config
import routes_files
import routes_inspections
import routes_legal
import routes_requests
import routes_students
import routes_withdrawals


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_config.bp)
    app.register_blueprint(routes_students.bp)
    app.register_blueprint(routes_withdrawals.bp)
    app.register_blueprint(routes_files.bp)
    app.register_blueprint(routes_requests.bp)
    app.register_blueprint(routes_inspections.bp)
    app.register_blueprint(routes_amendments.bp)
    app.register_blueprint(routes_legal.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        body, status = error_body(exc.error_id, exc.message), exc.http_status
        return jsonify(body), status

    @app.errorhandler(400)
    def _handle_bad_request(exc):
        return jsonify(error_body("ERR_VALIDATION", "The request body is malformed.")), 400

    @app.errorhandler(404)
    def _handle_not_found(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "The requested resource does not exist.")), 404

    @app.errorhandler(405)
    def _handle_method_not_allowed(exc):
        return jsonify(error_body("ERR_METHOD_NOT_ALLOWED",
                                  "The method is not allowed for this resource.")), 405

    @app.errorhandler(415)
    def _handle_unsupported_media(exc):
        return jsonify(error_body("ERR_VALIDATION",
                                  "The request body must be JSON.")), 400

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return _handle_not_found(exc)
        if status == 405:
            return _handle_method_not_allowed(exc)
        if status in (400, 415):
            return jsonify(error_body("ERR_VALIDATION", "The request is malformed.")), 400
        return jsonify(error_body("ERR_INTERNAL", exc.name)), status

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return jsonify(error_body("ERR_INTERNAL", str(exc) or "Internal server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
