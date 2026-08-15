"""Helicopter Tour Ops API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). All state is in-memory (store.py); every
process boot starts empty. No entity is seeded at startup.
"""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError
from routes_admin import bp as admin_bp
from routes_flights import bp as flights_bp
from routes_bookings import bp as bookings_bp
from routes_weather_complaints import bp as weather_complaints_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(admin_bp)
    app.register_blueprint(flights_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(weather_complaints_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response('ERR_NOT_FOUND', 404, 'Resource not found')

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response('ERR_NOT_FOUND', 404, 'Resource not found')

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response('ERR_INVALID_REQUEST', 400, f'Unexpected error: {err}')

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port, threaded=True)
