"""Logistics WMS Flask app entry point."""

import os

from flask import Flask, g

from core import ApiError, error_response, gen_request_id
from routes import bp


def create_app():
    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False

    @app.before_request
    def assign_request_id():
        g.request_id = gen_request_id()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response('ERR_NOT_FOUND', 'Route not found', 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response('ERR_NOT_FOUND', 'Method not allowed', 404)

    @app.errorhandler(400)
    def handle_bad_request(err):
        return error_response('ERR_INVALID_INPUT', str(getattr(err, 'description', 'Bad request')), 422)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # last-ditch
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response('ERR_INVALID_INPUT', f'Unexpected error: {err}', 422)

    app.register_blueprint(bp)
    return app


app = create_app()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=False)
