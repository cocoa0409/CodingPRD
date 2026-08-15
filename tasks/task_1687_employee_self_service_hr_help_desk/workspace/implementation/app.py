"""Entry point: Flask app, error handlers, route registration.

Storage is in-memory only (module-level dicts in db.py); the process boots
empty every time — the harness kills and re-launches via start.sh before each
test (per-test-server isolation), so no state may carry over and nothing is
seeded at startup.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_body
from routes import audit, categories, clock, dcrs, employees, kb, metrics, \
    staffing, surveys, teams_agents, tickets

API_PREFIX = '/hr-helpdesk'


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (employees, teams_agents, categories, kb, tickets, dcrs,
                   surveys, staffing, audit, metrics, clock):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err.error_id, err.message), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        return error_body('ERR_NOT_FOUND', 'resource not found'), 404

    @app.errorhandler(405)
    def handle_405(err):
        return error_body('ERR_NOT_FOUND', 'method not allowed'), 405

    @app.errorhandler(500)
    def handle_500(err):
        return error_body('ERR_INTERNAL', 'internal server error'), 500

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port, threaded=True)
