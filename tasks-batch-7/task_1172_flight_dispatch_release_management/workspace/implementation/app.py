"""Flight Dispatch Release API -- entry point, error handlers, route registration."""
import os
import traceback

from flask import Flask, jsonify

from errors import ApiError, err
from util import error_body

app = Flask(__name__)
app.json.sort_keys = False

import routes_core
import routes_legs
import routes_plans
import routes_ops
import routes_rel

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_legs.bp)
app.register_blueprint(routes_plans.bp)
app.register_blueprint(routes_ops.bp)
app.register_blueprint(routes_rel.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_body(e)


@app.errorhandler(404)
def handle_404(e):
    return error_body(err('ERR_NOT_FOUND'))


@app.errorhandler(405)
def handle_405(e):
    return error_body(err('ERR_INVALID_REQUEST', 'method not allowed'))


@app.errorhandler(Exception)
def handle_exception(e):
    traceback.print_exc()
    return error_body(err('ERR_INTERNAL', str(e)))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)
