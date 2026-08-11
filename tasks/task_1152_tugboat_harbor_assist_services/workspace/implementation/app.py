"""Tugboat Harbor Assist API — entry point, locking, error handlers."""
import os
import traceback

from flask import Flask

from db import store
from errors import ApiError
from util import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_refdata
import routes_jobs
import routes_assignments
import routes_pilotbookings
import routes_watch
import routes_safety
import routes_billing
import routes_clock

for mod in (routes_refdata, routes_jobs, routes_assignments, routes_pilotbookings,
            routes_watch, routes_safety, routes_billing, routes_clock):
    app.register_blueprint(mod.bp)


@app.before_request
def _acquire_lock():
    store.lock.acquire()


@app.teardown_request
def _release_lock(_exc):
    try:
        store.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _not_found(_e):
    return error_response(ApiError('ERR_NOT_FOUND', 404, 'resource not found'))


@app.errorhandler(405)
def _method_not_allowed(_e):
    return error_response(ApiError('ERR_NOT_FOUND', 404, 'resource not found'))


@app.errorhandler(Exception)
def _unhandled(e):
    traceback.print_exc()
    return error_response(ApiError('ERR_INVALID_REQUEST', 400, str(e)))


if __name__ == '__main__':
    app.run(host='0.0.0.0',
            port=int(os.environ.get('PORT', '10000')),
            threaded=True)
