"""Entry point: Flask app assembly, error handlers, lazy sweeps."""
import os

from flask import Flask

from common import ApiError, error_response, run_sweeps
import routes_core
import routes_equity
import routes_governance

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_equity.bp)
app.register_blueprint(routes_governance.bp)


@app.before_request
def _sweeps():
    run_sweeps()


@app.errorhandler(ApiError)
def _api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _not_found(e):
    return error_response(ApiError('ERR_NOT_FOUND', 'Resource not found'))


@app.errorhandler(405)
def _method_not_allowed(e):
    return error_response(ApiError('ERR_NOT_FOUND', 'Resource not found'))


@app.errorhandler(Exception)
def _unhandled(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError('ERR_INVALID_REQUEST', 'Malformed request'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
