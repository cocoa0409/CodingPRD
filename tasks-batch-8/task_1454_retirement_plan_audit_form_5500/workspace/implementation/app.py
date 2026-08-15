"""Retirement Plan Audit & Form 5500 Preparation API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask

from envelope import error_body
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes_engagements import bp as engagements_bp
    from routes_participants import bp as participants_bp
    from routes_contributions import bp as contributions_bp
    from routes_testing import bp as testing_bp
    from routes_filings import bp as filings_bp
    from routes_clock import bp as clock_bp

    for blueprint in (engagements_bp, participants_bp, contributions_bp,
                      testing_bp, filings_bp, clock_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_body('ERR_NOT_FOUND', 'Resource not found', 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_body('ERR_NOT_FOUND', 'Resource not found', 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_body('ERR_INTERNAL', str(err), 500)

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port, threaded=True)
