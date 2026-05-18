"""Flask application entry point for the Property Tax Assessment & Appeal API."""

import os

from flask import Flask, jsonify, request

from errors import APIError, raise_error
from middleware import authenticate
from response import error_response, success
from routes import register_routes


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _auth():
        # Allow OPTIONS through without auth (CORS preflight); none expected in tests
        if request.method == "OPTIONS":
            return None
        try:
            authenticate()
        except APIError as e:
            return error_response(e)
        return None

    @app.errorhandler(APIError)
    def _api_error(err: APIError):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_):
        try:
            raise_error("ERR_NOT_FOUND", "route not found")
        except APIError as e:
            return error_response(e)

    @app.errorhandler(405)
    def _method_not_allowed(_):
        try:
            raise_error("ERR_VALIDATION_FAILED", "method not allowed")
        except APIError as e:
            return error_response(e)

    @app.errorhandler(400)
    def _bad_request(_):
        try:
            raise_error("ERR_VALIDATION_FAILED", "bad request")
        except APIError as e:
            return error_response(e)

    @app.errorhandler(Exception)
    def _unhandled(e):
        # Surface unexpected errors as ERR_VALIDATION_FAILED to satisfy envelope
        try:
            raise_error("ERR_VALIDATION_FAILED", str(e) or "unexpected error")
        except APIError as err:
            return error_response(err)

    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
