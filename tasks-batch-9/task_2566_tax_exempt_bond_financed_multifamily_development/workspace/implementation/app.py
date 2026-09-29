"""Tax-Exempt Bond Financed Multifamily Development API.

A single Flask process holding all state in memory.  Nothing is seeded: every
row in the store is created by a client through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError, _default_message
from routes import agreements, bonds, certs_credit, clock, compliance, draws
from routes import onboarding, reads, units, volumecap


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (onboarding, volumecap, units, agreements, bonds, draws,
                   certs_credit, compliance, clock, reads):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "The HTTP method is not allowed for this path.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  _default_message("ERR_INVALID_REQUEST"), 400)
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "Request could not be handled.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
