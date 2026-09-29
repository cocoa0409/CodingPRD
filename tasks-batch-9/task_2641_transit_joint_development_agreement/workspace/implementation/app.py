"""Transit Joint Development Agreement API.

Flask application factory and error plumbing.  All state lives in process-local
dictionaries in store.py; nothing is ever seeded at startup.
"""

import os

from flask import Flask, jsonify

import envelope
import routes_agreement
import routes_federal
import routes_negotiation
import routes_ops
import routes_reads
import routes_sites
import routes_solicitation
from errors import ERROR_STATUS, ApiError


def _error_response(error_id, message, status):
    return jsonify(envelope.error(error_id, message)), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_reads.bp)
    app.register_blueprint(routes_sites.bp)
    app.register_blueprint(routes_solicitation.bp)
    app.register_blueprint(routes_negotiation.bp)
    app.register_blueprint(routes_negotiation.clock_bp)
    app.register_blueprint(routes_agreement.bp)
    app.register_blueprint(routes_federal.bp)
    app.register_blueprint(routes_ops.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return _error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return _error_response("ERR_NOT_FOUND", "No such route", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return _error_response("ERR_INVALID_REQUEST",
                               "Method not allowed for this route", 405)

    @app.errorhandler(415)
    def handle_415(_exc):
        return _error_response("ERR_INVALID_REQUEST",
                               "Request body must be JSON", 422)

    @app.errorhandler(400)
    def handle_400(_exc):
        return _error_response("ERR_INVALID_REQUEST", "Request is not well formed", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        app.logger.exception("unhandled error")
        return _error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
