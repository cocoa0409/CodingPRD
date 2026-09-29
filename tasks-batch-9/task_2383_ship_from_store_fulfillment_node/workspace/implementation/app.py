"""Ship-from-Store Fulfillment Node Network -- Flask application entry point.

Storage is in-memory only and starts completely empty on every boot; the
logical clock starts at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import execution, nodes, ops, orders, pickups, routing
from services import derive


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(nodes.bp)
    app.register_blueprint(pickups.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(routing.bp)
    app.register_blueprint(execution.bp)
    app.register_blueprint(ops.bp)

    @app.before_request
    def _capture_derived_state():
        # PRD 2.5: a change to a derived field is itself a mutation, so the
        # pre-request projection of every derived field is the diff baseline.
        g.pre = derive.capture()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return error_response("ERR_NOT_FOUND",
                              "The method is not allowed for this resource.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "The request payload or query is malformed.", 400)
        return error_response("ERR_NOT_FOUND", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error_response("ERR_INTERNAL", str(exc) or "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
