"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import authenticate
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth():
        authenticate()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_body(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_body(ERR_NOT_FOUND, "route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_body(ERR_INVALID_REQUEST, "method not allowed", 405)

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, ApiError):
            return error_body(e.error_id, e.message, e.http_status)
        return error_body(ERR_INVALID_REQUEST, f"unhandled error: {e}", 400)

    from routes import (clock, covered_persons, deals, restricted, blackout,
                        preclearance, exceptions, plans, confirmations, cases,
                        attestations, sweeps)
    for mod in (clock, covered_persons, deals, restricted, blackout,
                preclearance, exceptions, plans, confirmations, cases,
                attestations, sweeps):
        app.register_blueprint(mod.bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
