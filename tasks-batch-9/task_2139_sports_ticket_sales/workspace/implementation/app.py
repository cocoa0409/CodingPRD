"""Sports Ticket Sales Operations API - entry point.

In-memory storage only; the store starts empty on every boot and nothing is
seeded, preloaded or hardcoded at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
import ops
import routes_accounts
import routes_holds
import routes_market
import routes_orders
import routes_setup


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_setup.bp)
    app.register_blueprint(routes_accounts.bp)
    app.register_blueprint(routes_holds.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_market.bp)
    app.register_blueprint(ops.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", 404, "The requested route does not exist.")
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed for this route.")
        if exc.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST", 400, "The request body could not be parsed.")
        return error_response("ERR_INVALID_REQUEST", exc.code or 500, exc.description or "Request failed.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error")
        return error_response("ERR_INVALID_REQUEST", 500, "Internal server error: %s" % exc)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
