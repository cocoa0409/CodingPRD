"""Entry point: app factory, error handlers, route registration.

Boots cleanly from a fresh process on every invocation: the store is
in-memory only, starts empty, and the logical clock resets to
2026-05-01T00:00:00Z. Nothing is seeded.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import register_routes
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response(ApiError('ERR_NOT_FOUND', 404, 'Not found'))

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response(
            ApiError('ERR_METHOD_NOT_ALLOWED', 405, 'Method not allowed'))

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return error_response(
                ApiError('ERR_HTTP_{}'.format(exc.code), exc.code,
                         exc.description))
        return error_response(
            ApiError('ERR_INTERNAL', 500, 'Internal server error'))

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
            threaded=True)
