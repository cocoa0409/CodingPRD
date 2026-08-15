"""Entry point: Flask app, error handlers, route registration.

The store starts empty on every boot — no seeding, no preloading.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response
from routes import ops, accounts, applications, enrollments, dpas, payments
from routes import certificates, orders, funding, referrals

app = Flask(__name__)

for module in (ops, accounts, applications, enrollments, dpas, payments,
               certificates, orders, funding, referrals):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(_err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(_err):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(400)
def handle_400(_err):
    return error_response(ERR_INVALID_REQUEST, 400, "Invalid request")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
