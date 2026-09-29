"""Customer Success Renewal & Health Scoring API.

A single Flask process holding all state in memory.  Nothing is seeded: every row
comes into existence through a declared endpoint, so a fresh boot always starts
from an empty store.
"""
import os

from flask import Flask, jsonify

import response as resp
from errors import ApiError
from routes import (accounts, advocacy, coverage_assignments, csms, engagements,
                    escalations, expansion, forecasts, goals, milestones, ops,
                    save_plays, signals, sponsors)

BLUEPRINTS = (
    accounts.bp,
    csms.bp,
    coverage_assignments.bp,
    signals.bp,
    sponsors.bp,
    engagements.bp,
    goals.bp,
    milestones.bp,
    save_plays.bp,
    escalations.bp,
    forecasts.bp,
    expansion.bp,
    advocacy.bp,
    ops.bp,
)


def _error_response(error_id, message, status):
    return jsonify(resp.error_body(error_id, message)), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config['JSON_SORT_KEYS'] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return _error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return _error_response('ERR_INVALID_REQUEST',
                               'No route matches the requested path.', 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return _error_response('ERR_INVALID_REQUEST',
                               'The HTTP method is not allowed on this path.', 405)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return _error_response('ERR_INVALID_REQUEST',
                               'The request could not be parsed.', 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return _error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception('unhandled error')
        return _error_response('ERR_INVALID_REQUEST',
                               'The request could not be completed: %s' % exc, 500)

    return app


app = create_app()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port, threaded=True, debug=False,
            use_reloader=False)
