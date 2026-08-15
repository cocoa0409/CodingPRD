"""Nonprofit Board Governance & Compliance API — Flask entry point."""
import os

from flask import Flask

import store
from helpers import ApiError, error_envelope
from routes import bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False


@app.before_request
def _acquire_lock():
    store.lock.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        store.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_envelope(err)


@app.errorhandler(404)
def _handle_404(err):
    return error_envelope(ApiError('ERR_NOT_FOUND', 404, 'Resource not found'))


@app.errorhandler(405)
def _handle_405(err):
    return error_envelope(ApiError('ERR_NOT_FOUND', 404, 'Resource not found'))


@app.errorhandler(Exception)
def _handle_500(err):
    if isinstance(err, ApiError):
        return error_envelope(err)
    return error_envelope(ApiError('ERR_INTERNAL', 500, str(err)))


app.register_blueprint(bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
