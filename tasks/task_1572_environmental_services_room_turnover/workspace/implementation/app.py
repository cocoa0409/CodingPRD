"""Flask entry point: app wiring, global lock, error handlers."""
import os

from flask import Flask

import store as store_mod
from common import ApiError, check_headers, error_response
from routes_a import bp as bp_core
from routes_b import bp as bp_work
from routes_c import bp as bp_flow

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.before_request
def _before():
    store_mod.lock.acquire()
    check_headers()


@app.teardown_request
def _teardown(exc=None):
    try:
        store_mod.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _not_found(err):
    return error_response(ApiError('ERR_NOT_FOUND', 'Route not found', 404))


@app.errorhandler(405)
def _method_not_allowed(err):
    return error_response(ApiError('ERR_METHOD_NOT_ALLOWED', 'Method not allowed', 405))


@app.errorhandler(Exception)
def _generic_error(err):
    return error_response(ApiError('ERR_INTERNAL', 'Internal server error: %s' % err, 500))


app.register_blueprint(bp_core)
app.register_blueprint(bp_work)
app.register_blueprint(bp_flow)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')), threaded=True)
