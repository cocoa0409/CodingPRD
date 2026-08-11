"""Broker-Dealer AML & Account Opening API — Flask entry point.

In-memory only; the store starts empty on every boot. Reads PORT (default
10000), binds 0.0.0.0, runs in the foreground.
"""

import os

from flask import Flask

from errors import ApiError
from util import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes_core import bp as core_bp
    from routes_accounts import bp as accounts_bp
    from routes_compliance import bp as compliance_bp
    from routes_ops import bp as ops_bp
    app.register_blueprint(core_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(compliance_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response("ERR_INVALID_REQUEST", 404, "Resource or route not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", 500, "Internal error: %s" % e)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
