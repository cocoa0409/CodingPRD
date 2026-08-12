import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import err

from routes import clock, consignors, customers, instruments, appraisals, bids, orders
from routes import delivery, services, financing, warranties, restoration, events

app = Flask(__name__)

for module in (clock, consignors, customers, instruments, appraisals, bids, orders,
               delivery, services, financing, warranties, restoration, events):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err(e.error_id, e.message, e.status)


@app.errorhandler(HTTPException)
def handle_http_error(e):
    if e.code == 404:
        return err('ERR_NOT_FOUND', 'resource not found', 404)
    return err('ERR_INVALID_REQUEST', e.description or 'request error', e.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(e):
    return err('ERR_INVALID_REQUEST', 'internal error: %s' % e, 500)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
