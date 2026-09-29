"""Animation Studio Production Pipeline API.

Entry point: registers every route module, installs the error envelope handlers
and serves on $PORT. The in-memory store starts completely empty -- nothing is
seeded, preloaded or hardcoded here or anywhere else.
"""
import os

from flask import Flask, g

import routes_assets
import routes_deliverables
import routes_productions
import routes_render
import routes_rooms
import routes_shots
import routes_vendor
from helpers import ApiError, error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (routes_productions, routes_assets, routes_shots, routes_rooms,
               routes_render, routes_vendor, routes_deliverables):
    app.register_blueprint(module.bp)


@app.before_request
def _begin_request():
    # One accepted request advances a given row's version at most once, however
    # many cascade steps touch it.
    g._touched = set()


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(400)
def _handle_bad_request(_exc):
    return error_response('ERR_VALIDATION', 422, 'the request body is not valid JSON')


@app.errorhandler(404)
def _handle_not_found(_exc):
    return error_response('ERR_NOT_FOUND', 404, 'no such resource')


@app.errorhandler(405)
def _handle_method_not_allowed(_exc):
    return error_response('ERR_METHOD_NOT_ALLOWED', 405,
                          'that method is not allowed on this path')


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.http_status, exc.message)
    app.logger.exception('unhandled error')
    return error_response('ERR_INTERNAL', 500, str(exc))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
            threaded=True, debug=False, use_reloader=False)
