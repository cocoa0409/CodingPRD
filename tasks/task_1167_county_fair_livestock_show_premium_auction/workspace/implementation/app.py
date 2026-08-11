"""County Fair Livestock Show & Premium Auction API — Flask entry point."""
import os
import sys

from flask import Flask, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import store  # noqa: E402
from errors import ApiError  # noqa: E402
from response import error_response, success_object  # noqa: E402
from routes.fairs import bp as fairs_bp  # noqa: E402
from routes.people import bp as people_bp  # noqa: E402
from routes.entries import bp as entries_bp  # noqa: E402
from routes.show import bp as show_bp  # noqa: E402
from routes.auction import bp as auction_bp  # noqa: E402
from routes.compliance import bp as compliance_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(fairs_bp)
    app.register_blueprint(people_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(show_bp)
    app.register_blueprint(auction_bp)
    app.register_blueprint(compliance_bp)

    # Serialize all requests through one lock to keep the in-memory store
    # consistent under the threaded dev server.
    @app.before_request
    def _acquire_lock():
        store.lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            store.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ApiError('ERR_NOT_FOUND', 404, 'Resource not found'))

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ApiError('ERR_NOT_FOUND', 404, 'Resource not found'))

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(ApiError('ERR_INVALID_REQUEST', 400, str(e)))

    @app.get('/')
    def _root():
        return success_object({'status': 'ok'})

    return app


app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
