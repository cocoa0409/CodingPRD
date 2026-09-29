"""QDRO Processing API — Flask application entry point.

Storage is entirely in memory and starts empty on every boot: no database, no
file cache, and nothing seeded, preloaded or hardcoded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import routes_cases
import routes_drafts
import routes_holds
import routes_ops
import routes_participants
import routes_payees
import routes_plans
from envelope import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.register_blueprint(routes_plans.bp)
    app.register_blueprint(routes_participants.bp)
    app.register_blueprint(routes_cases.bp)
    app.register_blueprint(routes_drafts.bp)
    app.register_blueprint(routes_holds.bp)
    app.register_blueprint(routes_payees.bp)
    app.register_blueprint(routes_ops.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_NOT_FOUND", "No such resource or route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "That method is not allowed on this route.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return error_response(errors.ERR_INVALID_REQUEST,
                                  "The request could not be understood.", 400)
        return error_response("ERR_HTTP_%d" % (exc.code or 500),
                              exc.description or "Request failed.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
