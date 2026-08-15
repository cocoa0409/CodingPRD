"""Bulky Curbside Collection API — Flask entry point.

In-memory only; store starts empty on every boot (per-test-server isolation).
"""
import os
import threading

from flask import Flask

import response
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST

app = Flask(__name__)
app.url_map.strict_slashes = False

# Serialize all request handling: in-memory stores are mutated non-atomically
# across a transition, so interleaved requests must not observe half-applied state.
_lock = threading.RLock()


@app.before_request
def _acquire_lock():
    _lock.acquire()


@app.teardown_request
def _release_lock(exc):
    _lock.release()


@app.errorhandler(ApiError)
def _api_error(e):
    return response.err(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _not_found(e):
    return response.err(ERR_NOT_FOUND, 'Resource not found', 404)


@app.errorhandler(405)
def _method_not_allowed(e):
    return response.err(ERR_NOT_FOUND, 'Resource not found', 404)


@app.errorhandler(400)
def _bad_request(e):
    return response.err(ERR_INVALID_REQUEST, 'Malformed request', 400)


@app.errorhandler(Exception)
def _internal(e):
    if isinstance(e, ApiError):
        return response.err(e.error_id, e.message, e.http_status)
    return response.err(ERR_INVALID_REQUEST, f'Internal error: {e}', 500)


from routes import clock, households, amnesty, route_days, pickup_requests, fee_assessments, dumping_reports  # noqa: E402

for bp in (clock.bp, households.bp, amnesty.bp, route_days.bp,
           pickup_requests.bp, fee_assessments.bp, dumping_reports.bp):
    app.register_blueprint(bp)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')), threaded=True)
