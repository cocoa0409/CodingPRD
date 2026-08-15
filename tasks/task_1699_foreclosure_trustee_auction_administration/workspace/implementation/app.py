"""Foreclosure Trustee & Auction Administration API — Flask entry point.

Mounts all route blueprints, registers the ApiError handler, and serves on
0.0.0.0:$PORT (default 10000) in the foreground. The in-memory store starts
empty on every boot; nothing is seeded.
"""
import os

from flask import Flask

from errors import ApiError, err_not_found, err_invalid_request
from response import error_response
from routes.core import bp as core_bp
from routes.cases import bp as cases_bp
from routes.notices import bp as notices_bp
from routes.quotes import bp as quotes_bp
from routes.advances import bp as advances_bp
from routes.stays import bp as stays_bp
from routes.instructions import bp as instructions_bp
from routes.auction import bp as auction_bp
from routes.claims import bp as claims_bp
from routes.disbursements import bp as disbursements_bp


def create_app():
    app = Flask(__name__)

    for bp in (core_bp, cases_bp, notices_bp, quotes_bp, advances_bp,
               stays_bp, instructions_bp, auction_bp, claims_bp,
               disbursements_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(err_not_found("resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(err_invalid_request("method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        from flask import jsonify as _jsonify
        from response import _meta
        body = {"meta": _meta(), "response_type": "error",
                "data": {"error_id": "ERR_INVALID_REQUEST",
                         "message": "internal server error: " + str(err)}}
        return _jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
