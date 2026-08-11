import os

from flask import Flask, request

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response
from routes import register_routes
from services.sweep import sweep_expired


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    register_routes(app)

    @app.before_request
    def _sweep_on_read():
        # Held-slot TTL and round-deadline expiries are applied lazily on
        # reads (PRD 2.6: "on any read of a slot still in HELD").
        if request.method == 'GET':
            sweep_expired()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response(ERR_NOT_FOUND, 404, 'Resource not found')

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response(ERR_NOT_FOUND, 404, 'Resource not found')

    @app.errorhandler(400)
    def _bad_request(err):
        return error_response(ERR_INVALID_REQUEST, 400, 'Malformed request')

    @app.errorhandler(Exception)
    def _internal(err):
        return error_response(ERR_INVALID_REQUEST, 500, 'Internal error: %s' % err)

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
