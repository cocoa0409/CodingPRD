"""Flask application factory, error handlers and the logical clock endpoint.

Boots completely empty on every invocation: no entity data is seeded, preloaded
or read from disk anywhere in this process.
"""

import os

from flask import Flask

import bp_accounts
import bp_cards
import bp_catalog
import bp_elections
import bp_employer
import bp_orders
import bp_payroll
import bp_windows
from auth import authenticate
from errors import ApiError
from responses import error_response, object_response
from store import store
from validate import field, parse_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (bp_employer, bp_catalog, bp_windows, bp_accounts,
                   bp_elections, bp_orders, bp_cards, bp_payroll):
        app.register_blueprint(module.bp)

    @app.post("/_clock/set_current_utc")
    def set_current_utc():
        authenticate(["ProgramAdmin"])
        _body, values = parse_body([field("to_iso8601", "datetime", required=True)])
        store.set_clock(values["to_iso8601"])
        return object_response({})

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_NOT_FOUND", "The requested route does not exist.",
                              404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "The HTTP method is not allowed for this route.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
