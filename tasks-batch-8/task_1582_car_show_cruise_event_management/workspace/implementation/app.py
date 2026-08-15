"""Car Show & Cruise-In Event Management API - Flask entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.events import bp as events_bp
    from routes.registrants import bp as registrants_bp
    from routes.registrations import bp as registrations_bp
    from routes.score_sheets import bp as score_sheets_bp
    from routes.ballots import bp as ballots_bp
    from routes.awards import bp as awards_bp
    from routes.booths import bp as booths_bp

    app.register_blueprint(events_bp)
    app.register_blueprint(registrants_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(score_sheets_bp)
    app.register_blueprint(ballots_bp)
    app.register_blueprint(awards_bp)
    app.register_blueprint(booths_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response('ERR_NOT_FOUND', 404, 'Resource not found')

    @app.errorhandler(405)
    def handle_405(err):
        return error_response('ERR_NOT_FOUND', 404, 'Resource not found')

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.http_status, err.message)
        return error_response('ERR_VALIDATION', 400, str(err))

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)
