"""Infant & Child Sleep Consulting API — Flask entry point.

Mounts all resource blueprints under /sleep-consulting, wires the standard
error envelope, and serves on 0.0.0.0:$PORT (default 10000) in the foreground.
The store is purely in-memory and starts empty on every boot.
"""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError
from routes import (consultants, families, cases, questionnaires, plans,
                    packages, logs, sessions, messages, refunds, courses, clock)

API_PREFIX = '/sleep-consulting'


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response('ERR_NOT_FOUND', 404, 'Resource not found')

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response('ERR_METHOD_NOT_ALLOWED', 405,
                              'Method not allowed for this path')

    @app.errorhandler(400)
    def handle_bad_request(_err):
        return error_response('ERR_INVALID_REQUEST', 400, 'Bad request')

    @app.errorhandler(500)
    def handle_internal(_err):
        return error_response('ERR_INTERNAL', 500, 'Internal server error')

    for module in (consultants, families, cases, questionnaires, plans,
                   packages, logs, sessions, messages, refunds, courses, clock):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
