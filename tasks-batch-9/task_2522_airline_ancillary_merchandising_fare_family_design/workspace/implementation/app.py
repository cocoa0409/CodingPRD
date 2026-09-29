"""Airline Ancillary Merchandising API -- entry point.

Storage is entirely in-memory and starts empty on every boot: the harness
relaunches this process before each test, and every entity is created through
the declared API surface. Nothing is seeded here.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope as env
from errors import ApiError
from routes import catalog, dist, offers, ops, revenue, sell


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config['JSON_SORT_KEYS'] = False
    app.register_blueprint(catalog.bp)
    app.register_blueprint(ops.bp)
    app.register_blueprint(dist.bp)
    app.register_blueprint(sell.bp)
    app.register_blueprint(offers.bp)
    app.register_blueprint(revenue.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return env.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return env.error('ERR_NOT_FOUND', 'The requested route does not exist.', 404)
        if exc.code == 405:
            return env.error('ERR_METHOD_NOT_ALLOWED',
                             'The method is not allowed for this route.', 405)
        if exc.code in (400, 415):
            return env.error('ERR_INVALID_REQUEST',
                             'The request payload or query parameters are invalid.',
                             400)
        return env.error('ERR_INTERNAL', exc.description or 'Request failed.',
                         exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return env.error('ERR_INTERNAL', 'Internal server error.', 500)

    return app


app = create_app()


if __name__ == '__main__':
    # threaded so a client holding a keep-alive connection can never block
    # another client's request on the single-threaded dev server
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
            threaded=True, debug=False, use_reloader=False)
